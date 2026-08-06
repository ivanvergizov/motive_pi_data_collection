function updateRigidBodyVisualizer(hGraphics, pos, quat)

R = quatToRotMatMotiveToMatlab(quat);

transformedVertices = ...
    (R * hGraphics.baseVertices')' + pos;

localArrowDirection = [0, -0.2, 0];
globalArrowDirection = (R * localArrowDirection')';

tetCenter = mean(transformedVertices, 1);
arrowEnd = tetCenter + globalArrowDirection;

set(hGraphics.tetPatch, ...
    'Vertices', transformedVertices);

set(hGraphics.arrow3D, ...
    'XData', [tetCenter(1), arrowEnd(1)], ...
    'YData', [tetCenter(2), arrowEnd(2)], ...
    'ZData', [tetCenter(3), arrowEnd(3)]);

addpoints( ...
    hGraphics.trailingPath, ...
    pos(1), pos(2), pos(3));

end