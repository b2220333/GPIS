import logging
import numbers
import numpy as np
import os
import sys
import time

import experiment_config as ec
import json_serialization as jsons
import grasp
import graspable_object as go
import obj_file
import sdf_file
import feature_file

import IPython

INDEX_FILE = 'index.db'

class Database(object):
    def __init__(self, config):
        self._parse_config(config)
        self._create_datasets(config)

    def _parse_config(self, config):
        self.database_root_dir_ = config['database_dir']
        self.dataset_names_ = config['datasets']

    def _create_datasets(self, config):
        self.datasets_ = []
        for dataset_name in self.dataset_names_:
            self.datasets_.append(Dataset(dataset_name, config))

    @property
    def dataset_names(self):
        return self.dataset_names_

    @property
    def datasets(self):
        return self.datasets_

    def dataset(self, dataset_name=None):
        if dataset_name is None:
            return self.datasets[0] # return first element
        for dataset in self.datasets:
            if dataset.name == dataset_name:
                return dataset

class Dataset(object):
    def __init__(self, dataset_name, config):
        self._parse_config(config)

        self.dataset_name_ = dataset_name
        self.dataset_root_dir_ = os.path.join(self.database_root_dir_, self.dataset_name_)
        self.iter_count_ = 0

        # read in filenames
        self._read_data_keys()

    def _parse_config(self, config):
        self.database_root_dir_ = config['database_dir']

    def _read_data_keys(self, start=0, end=None):
        """Read in all the data keys from start to end in the index."""
        index_filename = os.path.join(self.dataset_root_dir_, INDEX_FILE)
        if not os.path.exists(index_filename):
            raise IOError('Index file does not exist! Invalid dataset: ' + self.dataset_root_dir_)

        self.data_keys_ = []
        self.data_categories_ = {}
        index_file_lines = open(index_filename, 'r').readlines()
        if end is None:
            end = len(index_file_lines)
        for i, line in enumerate(index_file_lines):
            if not (start <= i < end):
                continue

            tokens = line.split()
            if not tokens: # ignore empty lines
                continue

            self.data_keys_.append(tokens[0])
            if len(tokens) > 1:
                self.data_categories_[tokens[0]] = tokens[1]
            else:
                self.data_categories_[tokens[0]] = ''

    @property
    def name(self):
        return self.dataset_name_

    @property
    def data_keys(self):
        return self.data_keys_

    @property
    def dataset_root_dir(self):
        return self.dataset_root_dir_

    @staticmethod
    def sdf_filename(file_root):
        return file_root + '.sdf'

    @staticmethod
    def obj_filename(file_root):
        return file_root + '.obj'

    @staticmethod
    def json_filename(file_root):
        return file_root + '.json'

    @staticmethod
    def features_filename(file_root):
        return file_root + '.ftr'

    def read_datum(self, key):
        """Read in the GraspableObject3D corresponding to given key."""
        if key not in self.data_keys_:
            raise ValueError('Key %s not found in dataset %s' % (key, self.name))

        file_root = os.path.join(self.dataset_root_dir_, key)
        sdf_filename = Dataset.sdf_filename(file_root)
        obj_filename = Dataset.obj_filename(file_root)
        features_filename = Dataset.features_filename(file_root)

        # read in data
        sf = sdf_file.SdfFile(sdf_filename)
        sdf = sf.read()
        
        of = obj_file.ObjFile(obj_filename)
        mesh = of.read()

        if os.path.exists(features_filename):
            ff = feature_file.LocalFeatureFile(features_filename)
            features = ff.read()
        else:
            features = None

        return go.GraspableObject3D(sdf, mesh=mesh, features=features, key=key, model_name=obj_filename, category=self.data_categories_[key])

    def load_grasps(self, key, grasp_dir=None):
        """Loads a list of grasps from a file (grasp_dir/key.json).
        Params:
            key - string name of a graspable
            grasp_dir - string path to the grasp.json directory; defaults to
              self.dataset_root_dir_
        """
        if grasp_dir is None:
            grasp_dir = self.dataset_root_dir_
        path = os.path.join(grasp_dir, Dataset.json_filename(key))
        try:
            with open(path) as f:
                grasps = jsons.load(f)
        except:
            logging.warning('No grasp file found for key %s' %(key))
            return []
        return [grasp.ParallelJawPtGrasp3D.from_json(g) for g in grasps]

    def save_grasps(self, graspable, grasps):
        """Saves a list of grasps in the database.
        Params:
            graspable - the GraspableObject for the grasps
            grasps - a list of Grasps or a single Grasp to be saved
        """
        if not isinstance(grasps, list): # only one grasp
            grasps = [grasps]
        graspable_dict = {
            'key': graspable.key,
            'category': graspable.category,
            'grasps': [g.to_json() for g in grasps]
        }

        file_root = os.path.join(self.dataset_root_dir_, graspable.key)
        grasp_filename = Dataset.json_filename(file_root)
        # TODO: what should happen if grasp_filename already exists?
        with open(grasp_filename, 'w') as f:
            jsons.dump(grasps, f)

    def __getitem__(self, index):
        """ Index a particular object in the dataset """
        if isinstance(index, numbers.Number):
            if index < 0 or index >= len(self.data_keys_):
                raise ValueError('Index out of bounds. Dataset contains %d objects' %(len(self.data_keys_)))
            obj = self.read_datum(self.data_keys_[index])
            return obj
        elif isinstance(index, (str, unicode)):
            obj = self.read_datum(index)
            return obj

    def __iter__(self):
        """ Generate iterator """
        self.iter_count_ = 0 # NOT THREAD SAFE!
        return self
    
    def next(self):
        """ Read the next object file in the list """
        if self.iter_count_ >= len(self.data_keys_):
            raise StopIteration
        else:
            logging.info('Returning datum %s' %(self.data_keys_[self.iter_count_]))
            try:
                obj = self.read_datum(self.data_keys_[self.iter_count_])    
            except:
                logging.warning('Error reading %s. Skipping' %(self.data_keys_[self.iter_count_]))
                self.iter_count_ = self.iter_count_ + 1
                return self.next()

            self.iter_count_ = self.iter_count_ + 1
            return obj

class Chunk(Dataset):
    def __init__(self, config):
        self._parse_config(config)

        self.dataset_root_dir_ = os.path.join(self.database_root_dir_, self.dataset_name_)
        self.iter_count_ = 0

        # read in filenames
        self._read_data_keys(self.start, self.end)

    def _parse_config(self, config):
        super(Chunk, self)._parse_config(config)
        self.dataset_name_ = config['dataset']
        self.start = config['chunk_start']
        self.end = config['chunk_end']

def test_dataset():
    logging.getLogger().setLevel(logging.INFO)
    config_filename = 'cfg/basic_labelling.yaml'
    config = ec.ExperimentConfig(config_filename)

    db = Database(config)
    keys = []
    logging.info('Reading datset %s' %(db.datasets[0].name))
    for obj in db.datasets[0]:
        keys.append(obj.key)

    assert(len(keys) == 26)

def test_load_grasps():
    logging.getLogger().setLevel(logging.INFO)
    config_filename = 'cfg/basic_labelling.yaml'
    config = ec.ExperimentConfig(config_filename)

    key = 'feline_greenies_dental_treats'
    db = Database(config)
    apc = db.datasets[0]
    grasps = apc.load_grasps(key, 'results/gce_grasps/amazon_picking_challenge')
    graspable = apc[key]

if __name__ == '__main__':
    test_dataset()
