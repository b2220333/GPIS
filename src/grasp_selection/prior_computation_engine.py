import sys
sys.path.insert(0, 'src/grasp_selection/feature_vectors/')

from feature_database import FeatureDatabase
import kernels
import database
import feature_functions as ff
import feature_matcher as fm
import IPython
import logging
import registration as reg
import obj_file as of
import grasp_transfer as gt
import numpy as np
import time

class PriorComputationEngine:
	GRASP_TRANSFER_METHOD_NONE = 0
	GRASP_TRANSFER_METHOD_SHOT = 1
	GRASP_TRANSFER_METHOD_SCALE_XYZ = 2
	GRASP_TRANSFER_METHOD_SCALE_SINGLE = 3

	def __init__(self, db, config):
		self.feature_db = FeatureDatabase(config)
		self.db = db
		self.grasp_kernel = kernels.SquaredExponentialKernel(
			sigma=config['kernel_sigma'], l=config['kernel_l'])
		self.neighbor_kernel = kernels.SquaredExponentialKernel(
			sigma=1.0, l=(1/config['prior_neighbor_weight']))
		self.neighbor_distance = config['prior_neighbor_distance']
		self.num_neighbors = config['prior_num_neighbors']
		self.config = config
		self.grasp_kernel_tolerance = config['kernel_tolerance']
		self.prior_kernel_tolerance = config['prior_kernel_tolerance']

	def compute_priors(self, obj, candidates, nearest_features_name=None, grasp_transfer_method=2):
                start_time = time.time()
		if nearest_features_name == None:
			nf = self.feature_db.nearest_features()
		else:
			nf = self.feature_db.nearest_features(name=nearest_features_name)
                nf_time = time.time()
                logging.info('Nearest features took %f sec' %(nf_time - start_time))
		feature_vector = nf.project_feature_vector(self.feature_db.feature_vectors()[obj.key])
                fv_time = time.time()
                logging.info('Feature vectors took %f sec' %(fv_time - nf_time))
		neighbor_vector_dict = nf.k_nearest(feature_vector, k=self.num_neighbors) # nf.within_distance(feature_vector, dist=self.neighbor_distance)
                nv_time = time.time()
                logging.info('Neighbor vectors took %f sec' %(nv_time - fv_time))
		logging.info('Found %d neighbors!' % (len(neighbor_vector_dict)))
		return self._compute_priors_with_neighbor_vectors(obj, feature_vector, candidates, neighbor_vector_dict, grasp_transfer_method=grasp_transfer_method)

	def _compute_priors_with_neighbor_vectors(self, obj, feature_vector, candidates, neighbor_vector_dict, grasp_transfer_method=0,
                                                  alpha_prior=1.0, beta_prior=1.0):
                # load in all grasps and features
		logging.info('Loading features...')
                start_time = time.time()

                # transfer features
                logging.info('Using grasp transfer method %d' %(grasp_transfer_method))

		if grasp_transfer_method == self.GRASP_TRANSFER_METHOD_SHOT:
			reg_solver_dict = {}
			for neighbor_key in neighbor_vector_dict:
				reg_solver_dict[neighbor_key] = self._registration_solver(obj, neighbor_obj)
			self.reg_solver_dict = reg_solver_dict
		elif grasp_transfer_method == self.GRASP_TRANSFER_METHOD_SCALE_XYZ:
			self._create_feature_scales_xyz(obj, neighbor_vector_dict.keys())
		elif grasp_transfer_method == self.GRASP_TRANSFER_METHOD_SCALE_SINGLE:
			self._create_feature_scales_single(obj, neighbor_vector_dict.keys())

                transfer_time = time.time()
                logging.info('Grasp transfer precomp took %f sec' %(transfer_time - start_time))

                # extract all neighbor properties
                neighbor_key_list = neighbor_vector_dict.keys()
                neighbor_index_list = []
                neighbor_feature_list = []
                neighbor_grasp_list = []
                neighbor_kernel_list = []
                neighbor_distance_list = []
		for k, neighbor_key in enumerate(neighbor_vector_dict):
			if neighbor_key == obj.key:
				continue
                        logging.info('Loading features for %s' % (neighbor_key))
			neighbor_obj = self.db[neighbor_key]
			grasps, neighbor_features = self._load_grasps_and_features(neighbor_obj)

                        # put stuff in a list
                        neighbor_index_list.extend([k] * len(neighbor_features))
                        neighbor_kernel = self.neighbor_kernel.evaluate(feature_vector, neighbor_vector_dict[neighbor_key])
                        neighbor_distance = np.linalg.norm(feature_vector - neighbor_vector_dict[neighbor_key])
                        logging.info('Distance %f' %(neighbor_distance))
                        if neighbor_kernel < self.prior_kernel_tolerance:
                                neighbor_kernel = 0
                        neighbor_kernel_list.extend([neighbor_kernel]*len(neighbor_features))
                        neighbor_distance_list.append(neighbor_distance)
                        neighbor_grasp_list.extend(grasps)

                        # transfer all features
                        f_list = []
                        for features, grasp in zip(neighbor_features, grasps):
                                f_list.append(self._transfer_features(features, grasp, neighbor_key, grasp_transfer_method))                        
                        neighbor_feature_list.extend([f.phi for f in f_list])

                lf_time = time.time()			
                logging.info('Loading features took %f sec' %(lf_time - transfer_time))

                # create nn struct with neighbor features
                def phi(x):
                        return x
                error_radius = self.grasp_kernel.error_radius(self.grasp_kernel_tolerance)
                nn = kernels.KDTree(phi=phi)
                nn.train(neighbor_feature_list)
                logging.info('Num total features %d' %(len(neighbor_feature_list)))

                # create priors using the nn struct
		logging.info('Creating priors')
		prior_compute_start = time.clock()
                all_neighbor_kernels = [[]] * len(neighbor_key_list)
                all_neighbor_pfc_diffs = [[]] * len(neighbor_key_list)
		alpha_priors = []
		beta_priors = []
                num_neighbors = []
                out_rate = 50
		for k, candidate in enumerate(candidates):
			alpha = alpha_prior
			beta = beta_prior
                        if k % out_rate == 0:
                                logging.info('Creating priors for candidate %d' %(k))

                        # get neighbors within distance and compute kernels
                        neighbor_indices, _ = nn.within_distance(candidate.features, error_radius, return_indices=True)
                        num_neighbors.append(len(neighbor_indices))
                        for index in neighbor_indices:
                                successes = neighbor_grasp_list[index].successes
                                failures = neighbor_grasp_list[index].failures
                                object_kernel = neighbor_kernel_list[index]

                                grasp_kernel = self.grasp_kernel(candidate.features, neighbor_feature_list[index])
                                kernel_val = object_kernel * grasp_kernel

                                all_neighbor_kernels[neighbor_index_list[index]].append(kernel_val)
                                all_neighbor_pfc_diffs[neighbor_index_list[index]].append(abs(candidate.grasp.quality - neighbor_grasp_list[index].quality))
                                alpha += kernel_val * successes
                                beta += kernel_val * failures

			alpha_priors.append(alpha)
			beta_priors.append(beta)
		prior_compute_end = time.clock()
		logging.info('Created priors in %f sec' % (prior_compute_end - prior_compute_start))

		return alpha_priors, beta_priors, neighbor_key_list, neighbor_distance_list, all_neighbor_kernels, all_neighbor_pfc_diffs, num_neighbors

	def compute_grasp_kernels(self, obj, candidates, nearest_features_name=None, grasp_transfer_method=0):
		if nearest_features_name == None:
			nf = self.feature_db.nearest_features()
		else:
			nf = self.feature_db.nearest_features(name=nearest_features_name)
		feature_vector = nf.project_feature_vector(self.feature_db.feature_vectors()[obj.key])
		neighbor_vector_dict = nf.k_nearest(feature_vector, k=self.num_neighbors)
		neighbor_keys = []
		all_neighbor_pfc_diffs = []
		all_neighbor_kernels = []
		all_distances = []
		object_indices = range(0, 28)
		for neighbor_key in neighbor_vector_dict.keys():
			if neighbor_key == obj.key:
				continue
			neighbor_obj = self.db[neighbor_key]
			neighbor_pfc_diffs, neighbor_kernels, object_distance = self.kernel_info_from_neighbor(obj, candidates, neighbor_obj, grasp_transfer_method=grasp_transfer_method)
			all_neighbor_pfc_diffs.append(neighbor_pfc_diffs)
			all_neighbor_kernels.append(neighbor_kernels)
			all_distances.append(object_distance)
			neighbor_keys.append(neighbor_key)
		return neighbor_keys, all_neighbor_kernels, all_neighbor_pfc_diffs, all_distances

	def kernel_info_from_neighbor(self, obj, candidates, neighbor, grasp_transfer_method=0):
		feature_vectors = self.feature_db.feature_vectors()
		# nf = self.feature_db.nearest_features()
		feature_vector = np.array(feature_vectors[obj.key]) # nf.project_feature_vector(feature_vectors[obj.key])
		neighbor_vector = np.array(feature_vectors[neighbor.key]) # nf.project_feature_vector(feature_vectors[neighbor.key])
		print 'Loading features for %s' % (neighbor.key)
		grasps, all_features = self._load_grasps_and_features(neighbor)
		print 'Finished loading features'

		reg_solver = self._registration_solver(obj, neighbor)
		print 'Creating priors...'
		prior_compute_start = time.clock()
		neighbor_pfc_diffs = []
		neighbor_kernels = []
		object_distance = self.neighbor_kernel.evaluate(feature_vector, neighbor_vector)
		for candidate in candidates:
			alpha = 1.0
			beta = 1.0
			for neighbor_grasp, features in zip(grasps, all_features):
				features = self._transfer_features(features, neighbor_grasp, neighbor.key, grasp_transfer_method)
				grasp_distance = self.grasp_kernel(candidate.features, features.phi)
				neighbor_pfc_diffs.append(abs(candidate.grasp.quality - neighbor_grasp.quality))
				neighbor_kernels.append(grasp_distance*object_distance)
		prior_compute_end = time.clock()
		print 'Finished creating priors. TIME: %.2f' % (prior_compute_end - prior_compute_start)

		return neighbor_pfc_diffs, neighbor_kernels, object_distance

	def _load_grasps_and_features(self, obj):
		grasps = self.db.load_grasps(obj.key)
		feature_loader = ff.GraspableFeatureLoader(obj, self.db.name, self.config)
		all_features = feature_loader.load_all_features(grasps)
		return grasps, all_features

	def _registration_solver(self, source_obj, neighbor_obj):
		feature_matcher = fm.RawDistanceFeatureMatcher()
		correspondences = feature_matcher.match(source_obj.features, neighbor_obj.features)
		reg_solver = reg.SimilaritytfSolver()
		reg_solver.register(correspondences)
		reg_solver.add_source_mesh(source_obj.mesh)
		reg_solver.scale(neighbor_obj.mesh)
		return reg_solver

	def _create_feature_scales_xyz(self, obj, neighbor_keys):
		scales = {}
		principal_dims = obj.mesh.principal_dims()
		for neighbor_key in neighbor_keys:
			scale_vector = principal_dims / self.db[neighbor_key].mesh.principal_dims()
			scales[neighbor_key] = scale_vector
		self.scales = scales

	def _create_feature_scales_single(self, obj, neighbor_keys):
		scales = {}
		normalized_scale = np.mean(np.linalg.norm(np.array(obj.mesh.vertices_), axis=0))
		for neighbor_key in neighbor_keys:
			neighbor_normalized_scale = np.mean(np.linalg.norm(np.array(self.db[neighbor_key].mesh.vertices_), axis=0))
			scales[neighbor_key] = normalized_scale / neighbor_normalized_scale
		self.scales = scales

	def _transfer_features(self, features, neighbor_grasp, neighbor_key, grasp_transfer_method):
		if grasp_transfer_method == self.GRASP_TRANSFER_METHOD_SHOT:
			return self._transfer_features_shot(features, neighbor_grasp, self.reg_solver_dict[neighbor_key])
		elif grasp_transfer_method == self.GRASP_TRANSFER_METHOD_SCALE_XYZ:
			return self._transfer_features_by_scale(features, neighbor_key)
		elif grasp_transfer_method == self.GRASP_TRANSFER_METHOD_SCALE_SINGLE:
			return self._transfer_features_by_scale(features, neighbor_key)
		return features

	def _transfer_features_shot(self, features, grasp, reg_solver):
		grasp = gt.transformgrasp(grasp, reg_solver)
		features.extractors_[2].center_ = grasp.center
		features.extractors_[3].axis_ = grasp.axis
		return features

	def _transfer_features_by_scale(self, features, neighbor_key):
		old_center = features.extractors_[2].center_
		features.extractors_[2].center_ = old_center * self.scales[neighbor_key]
		return features


def test_prior_computation_engine():
	# TODO: fill in test
	# pce = PriorComputationEngine(nearest_features_path, feature_object_db_path, db, config)
	# obj = ...
	# candidates = ...
	# alpha_priors, beta_priors = pce.compute_priors(obj, candidates)
	# assert alpha_priors[0] == ... && beta_priors[0] == ...
	# assert alpha_priors[1] == ... && beta_priors[1] == ...
	pass

if __name__ == '__main__':
	test_prior_computation_engine()
