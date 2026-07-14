function hGraphics = RigidBodyVisualizer(axisLimits)

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

hGraphics = createRigidBodyGraphics('#4DBBD5');

end