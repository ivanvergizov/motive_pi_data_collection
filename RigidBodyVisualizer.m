function hGraphics = RigidBodyVisualizer(axisLimits, trailPoints)

if nargin < 2 || isempty(trailPoints)
    trailPoints = 500;
end

figure('Color', 'w');
grid on;
hold on;
view(3);
axis equal;

xlabel('X Position (m)');
ylabel('Y Position (m)');
zlabel('Vertical Height (m)');

if nargin > 0 && ~isempty(axisLimits)
    axis(axisLimits);
end

hGraphics = createRigidBodyGraphics([0.3010 0.7450 0.9330], trailPoints);

end