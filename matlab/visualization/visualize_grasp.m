function [] = visualize_grasp(grasp, shapeParams, shapeImage, scale, length,i,N,V,Names, ...
    plateWidth, gripWidth)
%VISUALIZE_GRASP

if nargin < 10
   plateWidth = 1; 
end
if nargin < 11
   gripWidth = size(shapeImage,1) / scale; 
end

d = size(grasp,1) / 2;
%graspPoints = create_ap_loa(grasp, gripWidth);

% find where these grasp points would contact the surface
numContacts = 2;
% figure(10);
% imshow(shapeImage);
% hold on;
[contacts, normals, bad ] = ...
    find_contact_points(grasp, numContacts, shapeParams.points, ...
        shapeParams.tsdf, shapeParams.normals, ...
        shapeParams.surfaceThresh, false, plateWidth, scale);
   
x1 = contacts(:,1);
x2 = contacts(:,2);
diff = x2 - x1;

% xNormGrid = reshape(shapeParams.normals(:,1), shapeParams.gridDim, shapeParams.gridDim);
% yNormGrid = reshape(shapeParams.normals(:,2), shapeParams.gridDim, shapeParams.gridDim);

% grad1 = -[xNormGrid(round(x1(2)), round(x1(1))); ...
%          yNormGrid(round(x1(2)), round(x1(1)))];
% grad2 = -[xNormGrid(round(x2(2)), round(x2(1))); ...
%          yNormGrid(round(x2(2)), round(x2(1)))];
grad1 = diff;
grad2 = -diff;

plot_grasp_arrows( shapeImage, x1, x2, grad1, grad2, scale, length,i,N,V, Names,shapeParams.com, plateWidth);

end
