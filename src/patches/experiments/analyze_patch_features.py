import numpy as np
import argparse
import yaml
import os
import matplotlib
matplotlib.use('Agg')#prevents using X server backend for matplotlib
import matplotlib.pyplot as plt
from patches_data_loader import PatchesDataLoader as PDL
import logging
import sys
_grasp_selection_path = os.path.join(os.path.dirname(__file__), '..', '..', 'grasp_selection')
sys.path.append(_grasp_selection_path)
import plotting
import IPython

def _ensure_dir_exists(dir):
    if not os.path.exists(dir):
        os.makedirs(dir)

def _plot_save_hist_bin(config, data, labels, feature_name, label_name, output_path):
    if len(np.unique(data)) != 2:
        logging.warn("Plotting histograms for binary data can only take in data with values 1 and 0. Skipping {0}".format(feature_name))
        return
    
    #read plot config
    font_size = config['plotting']['font_size']
    num_bins = config['plotting']['num_bins']
    dpi = config['plotting']['dpi']
    
    #get data and compute statistics
    positive_metrics = np.take(labels, np.argwhere(data == 1).flatten())
    negative_metrics = np.take(labels, np.argwhere(data == 0).flatten()) 
    
    min_range = min(np.min(positive_metrics), np.min(negative_metrics))
    max_range = max(np.max(positive_metrics), np.max(negative_metrics))
    
    pos_mean = np.mean(positive_metrics)
    pos_median = np.median(positive_metrics)
    pos_std = np.std(positive_metrics)

    neg_mean = np.mean(negative_metrics)
    neg_median = np.median(negative_metrics)
    neg_std = np.std(negative_metrics)

    msg_template = "mean:{:.3g}\nmedian:{:.3g}\nstd:{:.3g}"
    pos_msg = msg_template.format(pos_mean, pos_median, pos_std)
    neg_msg = msg_template.format(neg_mean, neg_median, neg_std)
    
    #plotting
    textbox_props = {'boxstyle':'square', 'facecolor':'white'}
    
    fig = plt.figure(figsize=(12, 5))
    fig.suptitle('Metric {0} Density'.format(label_name), fontsize=font_size)
    
    ax = plt.subplot("121")
    ax.set_title("{0}=1".format(feature_name), fontsize=font_size)
    plt.ylabel('Normalized Density', fontsize=font_size)
    plt.xlabel(label_name, fontsize=font_size)
    plotting.plot_histogram(positive_metrics, min_range=min_range, max_range=max_range, 
                                        num_bins=num_bins, normalize=True)
    ax.text(0.05, 0.95, pos_msg, transform=ax.transAxes, fontsize=14, verticalalignment='top', bbox=textbox_props, alpha=0.7)
    
    ax = plt.subplot("122")
    ax.set_title("{0}=0".format(feature_name), fontsize=font_size)
    plt.ylabel('Normalized Density', fontsize=font_size)
    plt.xlabel(label_name, fontsize=font_size)
    plotting.plot_histogram(negative_metrics, min_range=min_range, max_range=max_range, 
                                        num_bins=num_bins, normalize=True)
    ax.text(0.05, 0.95, neg_msg, transform=ax.transAxes, fontsize=14, verticalalignment='top', bbox=textbox_props, alpha=0.7)
    
    plt.subplots_adjust(top=0.8)
    
    figname = 'metric_{0}{1}histogram.pdf'.format(label_name, feature_name)
    logging.info("Saving {0}".format(figname))
    plt.savefig(os.path.join(output_path, figname), dpi=dpi)
    plt.close()

def _plot_save_scatter_pair(config, data, labels, features_pair, label_name, output_path):
    if data.shape[1] != 2:
        logging.warn("Scatter plot pair can only accept two-dimensional data. Skipping {0}".format(features_pair))
        return
        
    scatter_subsamples = config['plotting']['scatter_subsamples']
    line_width = config['plotting']['line_width']
    eps = config['plotting']['eps']
    font_size = config['plotting']['font_size']
    dpi = config['plotting']['dpi']
        
    #subsample data if needed
    p1, p2 = data[:,0], data[:,1]
    sub_inds = np.arange(data.shape[0])
    if data.shape[0] > scatter_subsamples:
        sub_inds = np.choose(scatter_subsamples, np.arange(data.shape[0]))
    p1_sub = p1[sub_inds]
    p2_sub = p2[sub_inds]
    labels_sub = labels[sub_inds]
        
    #compute best fit line
    A = np.c_[data, np.ones(data.shape[0])]
    b = labels
    w, _, _, _ = np.linalg.lstsq(A, b)
    rho = np.corrcoef(np.c_[data, labels].T)        
        
    min_p1, max_p1 = np.min(p1), np.max(p1)
    min_p2, max_p2 = np.min(p2), np.max(p2)
    x_vals = [min_p1, max_p1]
    y_vals = [w[2] + w[0] * min_p1 + w[1] * min_p2, w[2] + w[0] * max_p1 + w[1] * max_p2]
    
    #plot
    plt.figure()
    plt.scatter(p1_sub, labels_sub, c='b', s=50)
    plt.scatter(p2_sub, labels_sub, c='g', s=50)
    plt.plot(x_vals, y_vals, c='r', linewidth=line_width)
    plt.xlim(min(np.percentile(p1_sub, 1), np.percentile(p2_sub, 1)), max(np.percentile(p1_sub, 99), np.percentile(p2_sub, 99)))
    plt.ylim(min(labels_sub) - eps, max(labels_sub) + eps)
    plt.title('Metric {0} vs\nProjection Window Planarity'.format(label_name), fontsize=font_size)
    plt.xlabel('Deviation from Planarity', fontsize=font_size)
    plt.ylabel('Robustness', fontsize=font_size)
    leg = plt.legend(('Best Fit Line (rho={:.3g})'.format(rho[2,0]), features_pair[0], features_pair[1]), loc='best', fontsize=12)
    leg.get_frame().set_alpha(0.7)
    figname = 'metric_{0}{1}{2}scatter.pdf'.format(label_name, features_pair[0], features_pair[1])
    
    logging.info("Saving {0}".format(figname))
    plt.savefig(os.path.join(output_path, figname), dpi=dpi)
    plt.close()
    
    
def analyze_patch_features(config, input_path, output_path):
    #load data
    features_set_hist_bin = PDL.get_include_set_from_dict(config['feature_prefixes_hist_bin'])
    
    features_set_scatter_pair = []
    pair_configs = config['feature_prefixes_scatter_pair']
    for pair_config in pair_configs:
        if pair_config['use']:
            features_set_scatter_pair.append(set(pair_config['pair']))

    labels_set = PDL.get_include_set_from_dict(config['label_prefixes'])
    
    features_set = [features_set_hist_bin]
    features_set.extend(features_set_scatter_pair)
    features_set = set.union(*features_set)
    
    pdl = PDL(0.25, input_path, eval(config['file_nums']), features_set, set(), labels_set, split_by_objs=False)
    
    for label_name in labels_set:
        labels = pdl._raw_data[label_name]
        
        for feature_name in features_set_hist_bin:
            _plot_save_hist_bin(config, pdl._raw_data[feature_name], labels, feature_name, label_name, output_path)
        
        for features_pair in features_set_scatter_pair:
            features_pair = list(features_pair)
            features_pair.sort()
            _plot_save_scatter_pair(config, pdl.get_partial_raw_data(tuple(features_pair)), labels, features_pair, label_name, output_path)
    
if __name__ == '__main__':
    #read args
    parser = argparse.ArgumentParser()
    parser.add_argument('config')
    parser.add_argument('input_path')
    parser.add_argument('output_path')
    args = parser.parse_args()
    
    logging.getLogger().setLevel(logging.INFO)
    
    with open(args.config) as config_file:
        config = yaml.safe_load(config_file)
    
    _ensure_dir_exists(args.output_path)
    
    analyze_patch_features(config, args.input_path, args.output_path)