import gurobipy as gb
import numpy as np
import pyhull.convex_hull as cvh
import sys
import time

import grasp as g
import graspable_object as go
import obj_file
import sdf_file

import logging
import matplotlib.pyplot as plt
import mayavi.mlab as mv

import IPython

class PointGraspMetrics3D:

    @staticmethod
    def grasp_quality(grasp, obj, method = 'force_closure', soft_fingers = False, friction_coef = 0.5, num_cone_faces = 8, params = None):
        if not isinstance(grasp, g.PointGrasp):
            raise ValueError('Must provide a point grasp object')
        if not isinstance(obj, go.GraspableObject3D):
            raise ValueError('Must provide a 3D graspable object')
        if not hasattr(PointGraspMetrics3D, method):
            raise ValueError('Illegal point grasp metric specified')
        
        # get point grasp contacts
        contacts_found, contacts = grasp.close_fingers(obj)
        if not contacts_found:
            logging.debug('Contacts not found')
            return -np.inf

        # add the forces, torques, etc at each contact point
        num_contacts = contacts.shape[0]
        forces = np.zeros([3,0])
        torques = np.zeros([3,0])
        normals = np.zeros([3,0])
        for i in range(num_contacts):
            contact = contacts[i,:]
            force_success, contact_forces, contact_outward_normal = obj.contact_friction_cone(contact, num_cone_faces=num_cone_faces,
                                                                                              friction_coef=friction_coef)

            if not force_success:
                logging.debug('Force computation failed')
                continue

            torque_success, contact_torques = obj.contact_torques(contact, contact_forces)
            if not force_success:
                logging.debug('Torque computation failed')
                continue

            forces = np.c_[forces, contact_forces]
            torques = np.c_[torques, contact_torques]
            normals = np.c_[normals, -contact_outward_normal] # store inward pointing normals

        if normals.shape[1] == 0:
            logging.debug('No normals')
            return -np.inf

        # evaluate the desired quality metric
        Q_func = getattr(PointGraspMetrics3D, method)
        quality = Q_func(forces, torques, normals, soft_fingers, params)
        return quality

    @staticmethod
    def grasp_matrix(forces, torques, normals, soft_fingers=False, params = None):
        num_forces = forces.shape[1]
        num_torques = torques.shape[1]
        if num_forces != num_torques:
            raise ValueError('Need same number of forces and torques')

        num_cols = num_forces
        if soft_fingers:
            num_normals = 1
            if normals.ndim > 1:
                num_normals = normals.shape[1]
            num_cols = num_cols + num_normals

        G = np.zeros([6, num_cols])
        for i in range(num_forces):
            G[:3,i] = forces[:,i] 
            G[3:,i] = torques[:,i]

        if soft_fingers:
            G[3:,-num_normals:] = normals  
        return G

    @staticmethod
    def force_closure(forces, torques, normals, soft_fingers=False, params=None):
        """ Force closure """
        eps = 1e-2
        if params is not None:
            eps = params['eps']

        G = PointGraspMetrics3D.grasp_matrix(forces, torques, normals, soft_fingers)
        min_norm = PointGraspMetrics3D.min_norm_vector_in_facet(G)
        return 1 * (min_norm < eps) # if greater than eps, 0 is outside of hull 

    @staticmethod
    def min_singular(forces, torques, normals, soft_fingers=False, params=None):
        """ Min singular value of grasp matrix - measure of wrench that grasp is "weakest" at resisting """
        G = PointGraspMetrics3D.grasp_matrix(forces, torques, normals, soft_fingers)
        _, S, _ = np.linalg.svd(G)
        min_sig = S[5]
        return min_sig

    @staticmethod
    def wrench_volume(forces, torques, normals, soft_fingers=False, params=None):
        """ Volume of grasp matrix singular values - score of all wrenches that the grasp can resist """
        k = 1
        if params is not None:
            k = params['k']

        G = PointGraspMetrics3D.grasp_matrix(forces, torques, normals, soft_fingers)
        _, S, _ = np.linalg.svd(G)
        sig = S
        return k * np.sqrt(np.prod(sig))

    @staticmethod
    def grasp_isotropy(forces, torques, normals, soft_fingers=False, params=None):
        """ Condition number of grasp matrix - ratio of "weakest" wrench that the grasp can exert to the "strongest" one """
        G = PointGraspMetrics3D.grasp_matrix(forces, torques, normals, soft_fingers)
        _, S, _ = np.linalg.svd(G)
        max_sig = S[0]
        min_sig = S[5]
        isotropy = min_sig / max_sig
        if np.isnan(isotropy) or np.isinf(isotropy):
            return 0
        return isotropy

    @staticmethod
    def ferrari_canny_L1(forces, torques, normals, soft_fingers=False, params=None):
        """ The Ferrari-Canny L-infinity metric """
        eps = 1e-2
        if params is not None:
            eps = params['eps']

        # create grasp matrix
        G = PointGraspMetrics3D.grasp_matrix(forces, torques, normals, soft_fingers)
        s = time.clock()
        hull = cvh.ConvexHull(G.T, joggle=not soft_fingers)
        e = time.clock()
        logging.info('Convex hull took %f sec' %(e-s))

        if len(hull.vertices) == 0:
            logging.warning('Convex hull could not be computed')
            return -sys.float_info.max

        # determine whether or not zero is in the convex hull
        min_norm_in_hull = PointGraspMetrics3D.min_norm_vector_in_facet(G)

        # if norm is greater than 0 then forces are outside of hull
        if min_norm_in_hull > eps:
            return -min_norm_in_hull

        # find minimum norm vector across all facets of convex hull
        min_dist = sys.float_info.max
        for v in hull.vertices:
            facet = G[:, v]
            dist = PointGraspMetrics3D.min_norm_vector_in_facet(facet)
            if dist < min_dist:
                min_dist = dist

        return min_dist

    @staticmethod
    def min_norm_vector_in_facet(facet):
        eps = 1e-4
        dim = facet.shape[1] # num vertices in facet

        # create alpha weights for vertices of facet
        G = facet.T.dot(facet)
        G = G + eps * np.eye(G.shape[0])
        m = gb.Model("qp")
        m.params.OutputFlag = 0
        m.modelSense = gb.GRB.MINIMIZE
        
        alpha = [m.addVar(name="m"+str(v)) for v in range(dim)]
        alpha = np.array(alpha)
        m.update()

        # quadratic cost for Euclidean distance
        obj = alpha.T.dot(G).dot(alpha)
        m.setObjective(obj)    

        # sum constraint to enforce convex combinations of vertices
        ones_v = np.ones(dim)
        cvx_const = ones_v.T.dot(alpha)
        m.addConstr(cvx_const, gb.GRB.EQUAL, 1.0, "c0")

        # greater than zero constraint
        for i in range(dim):
            m.addConstr(alpha[i], gb.GRB.GREATER_EQUAL, 0.0)

        # solve objective
        m.optimize()
        min_norm = obj.getValue()
        return min_norm

def test_gurobi_qp():
    np.random.seed(100)
    dim = 20
    forces = 2 * (np.random.rand(3, dim) - 0.5)
    torques = 2 * (np.random.rand(3, dim) - 0.5)
    normal = 2 * (np.random.rand(3,1) - 0.5)
    G = PointGraspMetrics3D.grasp_matrix(forces, torques, normal)

    G = forces.T.dot(forces)
    m = gb.Model("qp")
    m.modelSense = gb.GRB.MINIMIZE
    alpha = [m.addVar(name="m"+str(v)) for v in range(dim)]
    alpha = np.array(alpha)
    m.update()

    obj = alpha.T.dot(G).dot(alpha)
    m.setObjective(obj)    

    ones_v = np.ones(dim)
    cvx_const = ones_v.T.dot(alpha)
    m.addConstr(cvx_const, gb.GRB.EQUAL, 1.0, "c0")
    
    for i in range(dim):
        m.addConstr(alpha[i], gb.GRB.GREATER_EQUAL, 0.0)

    m.optimize()
    for v in m.getVars():
        print('Var %s: %f'%(v.varName, v.x))

def test_ferrari_canny_L1_synthetic():
    np.random.seed(100)
    dim = 20
    forces = 2 * (np.random.rand(3, dim) - 0.5)
    torques = 2 * (np.random.rand(3, dim) - 0.5)
    normal = 2 * (np.random.rand(3,1) - 0.5)
    
    start_time = time.clock()
    fc = PointGraspMetrics3D.ferrari_canny_L1(forces, torques, normal, soft_fingers=True)
    end_time = time.clock()
    fc_comp_time = end_time - start_time
    print 'FC Quality: %f' %(fc)
    print 'Computing FC took %f sec' %(fc_comp_time)

def test_quality_metrics():
    np.random.seed(100)
    
    mesh_file_name = 'data/test/meshes/Co_clean.obj'
    sdf_3d_file_name = 'data/test/sdf/Co_clean.sdf'

    sf = sdf_file.SdfFile(sdf_3d_file_name)
    sdf_3d = sf.read()
    of = obj_file.ObjFile(mesh_file_name)
    mesh_3d = of.read()
    graspable = go.GraspableObject3D(sdf_3d, mesh = mesh_3d)

    z_vals = np.linspace(-0.025, 0.025, 3)
    for i in range(z_vals.shape[0]):
        print 'Evaluating grasp with z val %f' %(z_vals[i])
        grasp_center = np.array([0, 0, z_vals[i]])
        grasp_axis = np.array([0, 1, 0])
        grasp_width = 0.1
        grasp = g.ParallelJawPtGrasp3D(grasp_center, grasp_axis, grasp_width)
    
        qualities = []
        metrics = ['force_closure', 'min_singular', 'wrench_volume', 'grasp_isotropy', 'ferrari_canny_L1']
        for metric in metrics:
            q = PointGraspMetrics3D.grasp_quality(grasp, graspable, metric, soft_fingers=True)
            qualities.append(q)
            print 'Grasp quality according to %s: %f' %(metric, q)

        grasp.visualize(graspable)
        graspable.visualize()
        mv.show()

    IPython.embed()

if __name__ == '__main__':
    logging.getLogger().setLevel(logging.ERROR)
#    test_gurobi_qp()
#    test_ferrari_canny_L1_synthetic()
    test_quality_metrics()
 
