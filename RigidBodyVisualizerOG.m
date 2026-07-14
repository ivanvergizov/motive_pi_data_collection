function obj = RigidBodyVisualizerOG(axisLimits)
% RIGIDBODYVISUALIZER Constructor-like helper structure for shared graphics
obj.initWindow   = @(limits) initWindow(limits);
obj.updateFrame  = @(hGraphics, pos, quat) updateFrame(hGraphics, pos, quat);
end

function hGraphics = initWindow(axisLimits)S
% 1. Local Geometry Settings (Motive Y-up local frame)
scale = 0.15;
baseVertices = scale * [ 0, 1, 0; -1, -0.5, -0.6; 1, -0.5, -0.6; 0, -0.5, 1 ];

% Remap local coordinates to match MATLAB's Z-up environment
baseVertices_matlab = [baseVertices(:,1), baseVertices(:,3), baseVertices(:,2)];
faces = [1, 2, 3; 1, 3, 4; 1, 4, 2; 2, 3, 4];

% 2. Setup Figure Environment
figure('Color', 'w');
grid on; hold on; view(3);
axis equal;
xlabel('X Position (m)'); ylabel('Y Position (m)'); zlabel('Vertical Height (m)');

if nargin > 0 && ~isempty(axisLimits)
    axis(axisLimits);
end

% 3. Initialize Graphic Objects
hGraphics.tetPatch = patch('Vertices', baseVertices_matlab, 'Faces', faces, ...
    'FaceColor', '#4DBBD5', 'FaceAlpha', 0.8, 'EdgeColor', 'k');
hGraphics.arrow3D = quiver3(0, 0, 0, 0, 0, 0, 'Color', 'r', 'LineWidth', 3);
hGraphics.trailingPath = animatedline('Color', 'b', 'LineWidth', 1, 'LineStyle', ':');
hGraphics.baseVertices = baseVertices_matlab; % Store base shape to use in update
end

function updateFrame(hGraphics, pos, quat)
% pos:  [X, Y, Z] workspace remapped position
% quat: [W, X, Y, Z] quaternion format

% 1. Compute specialized remapped rotation matrix
R_matlab = quatToRotMat(quat);

% 2. Transform shape vertices
transformedVertices = (R_matlab * hGraphics.baseVertices')' + pos;

% 3. Calculate local arrow directions
localArrowDirection = [0, -0.2, 0];
globalArrowDirection = (R_matlab * localArrowDirection')';
tetCenter = mean(transformedVertices, 1);

% 4. Dynamically push to graphic handles
set(hGraphics.tetPatch, 'Vertices', transformedVertices);
set(hGraphics.arrow3D, 'XData', tetCenter(1), 'YData', tetCenter(2), 'ZData', tetCenter(3), ...
    'UData', globalArrowDirection(1), 'VData', globalArrowDirection(2), 'WData', globalArrowDirection(3));
addpoints(hGraphics.trailingPath, pos(1), pos(2), pos(3));
drawnow;
end

function R_matlab = quatToRotMat(q)
w = q(1); x = q(2); y = q(3); z = q(4);

R = [1 - 2*(y^2 + z^2), 2*(x*y - w*z), 2*(x*z + w*y); ...
    2*(x*y + w*z), 1 - 2*(x^2 + z^2), 2*(y*z - w*x); ...
    2*(x*z - w*y), 2*(y*z + w*x), 1 - 2*(x^2 + y^2)];

% Remap the rotation matrix directions to match the Z-up workspace conversion
R_matlab = [ R(1,1), R(1,3), R(1,2); ...
    R(3,1), R(3,3), R(3,2); ...
    R(2,1), R(2,3), R(2,2) ];
end
