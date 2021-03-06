% script for setting up and running an antipodal experiment

close all;
load('Grasp.mat')
dim = 25;
dataDir = 'data/google_update_versions';
filename = 'measure_cup';
outputDir = 'results/google_objects/test';
newShape = false;
scale = 2;

grip_point1 = [12.5 1; 12.5 25];

grip_point2 = [12.5 25; 12.5 1];

%% experiment config
experimentConfig = struct();
experimentConfig.graspIters = 5;
experimentConfig.frictionCoef = 0.5;
experimentConfig.surfaceThresh = 0.15;

%% variance parameters
varParams = struct();
varParams.y_thresh1_low = 12.5;
varParams.y_thresh2_low = dim;
varParams.y_thresh3_low = dim;

varParams.y_thresh1_high = 30;
varParams.y_thresh2_high = 0;
varParams.y_thresh3_high = 0;

varParams.x_thresh1_low = 15;
varParams.x_thresh2_low = dim;
varParams.x_thresh3_low = dim;

varParams.x_thresh1_high = 25;
varParams.x_thresh2_high = 0;
varParams.x_thresh3_high = 0;
% varParams.y_thresh1_low = dim;
% varParams.y_thresh2_low = dim;
% varParams.y_thresh1_high = 0;
% varParams.y_thresh2_high = 0;
% varParams.x_thresh1_low = dim;
% varParams.x_thresh2_low = dim;
% varParams.x_thresh1_high = 0;
% varParams.x_thresh2_high = 0;

varParams.occlusionScale = 1000;
varParams.noiseScale = 0.05;
varParams.interiorRate = 0.4;
varParams.specularNoise = false;
varParams.sparsityRate = 0.0;
varParams.sparseScaling = 1000;
varParams.edgeWin = 0;
varParams.noiseGradMode = 'None';
varParams.horizScale = 1;
varParams.vertScale = 1;

%% training parameters
trainingParams = struct();
trainingParams.activeSetMethod = 'LevelSet';
trainingParams.activeSetSize = 150;
trainingParams.beta = 10;
trainingParams.numIters = 1;
trainingParams.eps = 1e-2;
trainingParams.levelSet = 0;
trainingParams.surfaceThresh = 0.1;
trainingParams.scale = scale;
trainingParams.numSamples = 20;
trainingParams.hyp = struct();
trainingParams.hyp.cov = [0.6, 0];
trainingParams.hyp.mean = zeros(3, 1);
trainingParams.hyp.lik = log(0.1);


%% optimization parameters
cf = cos(atan(experimentConfig.frictionCoef));

cfg = struct();
cfg.max_iter = 10;
cfg.max_merit_coeff_increases = 5;
cfg.merit_coeff_increase_ratio = 10;
cfg.initial_penalty_coeff = 1.0;
cfg.initial_trust_box_size = 5;
cfg.trust_shrink_ratio = .75;
cfg.trust_expand_ratio = 2.0;
cfg.min_approx_improve = 0.1;
cfg.min_trust_box_size = 0.1;
cfg.callback = @plot_surface_grasp_points;
cfg.full_hessian = true;
cfg.cnt_tolerance = 1e-4;
cfg.ineq_tolerance = 1e-2;%[1e-2; 1e-2];
cfg.eq_tolerance = [1e-1; 1e-1; 5e-2; 5e-2; 1-cf; 1-cf; 2.5e-1];
cfg.com_tol = 2.0;
cfg.scale = scale;
cfg.min_init_dist = 5;
cfg.lambda = 0.00;
cfg.nu = 0.00;
cfg.fric_coef = 0; % use no-slip constraint to force antipodality but allow solutions within the friction cone

% % run experiment
% [ gpModel, shapeParams,img] = ...
%     run_gpis_2D_experiment(dim, filename, dataDir, ...
%                              outputDir, newShape, ...
%                              varParams, trainingParams,experimentConfig);
[gpModel, shapeParams, shapeSamples, constructionResults] = load_experiment_object(filename, dataDir, scale);
img.mean = constructionResults.newSurfaceImage;
figure; 
imshow(img.mean)

H = high_res_gpis(img.mean,4); 
figure; 
imshow(H)

[cp cp_mc] = get_random_grasp(shapeParams.gridDim,shapeParams.gridDim);

single_grasp(gpModel,shapeParams,cp,img,experimentConfig)

%[T_Q,contacts,HIST] = Run_Comp(experimentConfig,gpModel,shapeParams,img,constructionResults,Grasp);
% [loa_1,Norms,pc_1,pn_1] = Compute_Distributions(gpModel,shapeParams,grip_point1,img);
% 
% [loa_2,Norms,pc_2,pn_2] = Compute_Distributions(gpModel,shapeParams,grip_point2,img);
% 
% ca  = atan(experimentConfig.frictionCoef);
% fc = experimentConfig.frictionCoef;
% [E_Q,lb] = compute_lb( loa_1,loa_2,Norms,pc_1,pn_1,pc_2,pn_2, shapeParams.com,ca,fc,gpModel);