function hGraphics = createRigidBodyGraphics(bodyColor, maxTrailPoints)

if nargin < 2 || isempty(maxTrailPoints)
    maxTrailPoints = 500;
end

scale = 0.15;

baseVerts = scale * [
    0,  1,    0;
    -1, -0.5, -0.6;
    1, -0.5, -0.6;
    0, -0.5,  1
    ];

baseVerts = [
    baseVerts(:,1), ...
    baseVerts(:,3), ...
    baseVerts(:,2)
    ];

faces = [
    1, 2, 3;
    1, 3, 4;
    1, 4, 2;
    2, 3, 4
    ];

hGraphics.tetPatch = patch( ...
    'Vertices', baseVerts, ...
    'Faces', faces, ...
    'FaceColor', bodyColor, ...
    'FaceAlpha', 0.7, ...
    'EdgeColor', 'k');

hGraphics.arrow3D = plot3( ...
    [0 0], [0 0], [0 0], ...
    'Color', 'r', ...
    'LineWidth', 2);

hGraphics.trailingPath = animatedline( ...
    'Color', bodyColor, ...
    'LineWidth', 1, ...
    'LineStyle', ':', ...
    'MaximumNumPoints', maxTrailPoints);

hGraphics.baseVertices = baseVerts;

end