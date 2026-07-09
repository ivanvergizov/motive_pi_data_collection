% --- MATLAB LIVE PLOTTER (MULTI-BODY COMPATIBLE) ---
if exist('u', 'var')
    clear u;
end

% Initialize Visualizer Engine
vis = RigidBodyVisualizer();

% Setup a master figure environment
fig = figure('Name', 'OptiTrack Multi-Body Live Stream', 'NumberTitle', 'off', 'Color', 'w');
grid on; hold on; view(3); axis equal;
xlabel('X Position (m)'); ylabel('Y Position (m)'); zlabel('Vertical Height (m)');
axis([-3 3 -3 3 -0.5 2]); 
title('Live Multi-Rigid Body Tracking');

% Create a dynamic Map to store graphic objects for each unique ID
% Key = Rigid Body ID (double), Value = hGraphics structure
activeBodies = containers.Map('KeyType', 'double', 'ValueType', 'any');

% Open Port 7000
u = udpport("LocalPort", 7000); 
disp('Listening on Port 7000. Multi-Body mode active.');
clc;

printCounter = 0;

try
    while ishandle(fig)
        % Note: We no longer flush the entire buffer blindly. 
        % We read packets sequentially so we don't accidentally miss any IDs.
        while u.NumBytesAvailable > 0
            raw_data = read(u, 1, "string"); % Read one UDP packet line at a time
            
            if raw_data ~= ""
                split_data = split(raw_data, ",");
                
                if length(split_data) == 8
                    rb_id = double(split_data(1));
                    qX    = double(split_data(2));
                    qY    = double(split_data(3));
                    qZ    = double(split_data(4));
                    qW    = double(split_data(5));
                    rawX  = double(split_data(6));
                    rawY  = double(split_data(7));
                    rawZ  = double(split_data(8));
                    
                    % Workspace axis remapping (Motive Y-up to MATLAB Z-up)
                    x_mat = rawX;
                    y_mat = rawZ; 
                    z_mat = rawY; 
                    
                    if ~isnan(x_mat) && ~isnan(y_mat) && ~isnan(z_mat)
                        currentPos = [x_mat, y_mat, z_mat];
                        currentQuat = [qW, qX, qY, qZ];
                        
                        % --- DYNAMIC ID CHECK ---
                        if ~isKey(activeBodies, rb_id)
                            % First time seeing this ID! Initialize a new shape.
                            % Accessing the sub-initialization logic directly into current figure context
                            disp(['Detected new Rigid Body ID: ', num2str(rb_id)]);
                            
                            % Generate a random distinct color for this specific body
                            randomColor = rand(1, 3); 
                            
                            % Initialize shapes without spawning a brand new figure window
                            scale = 0.15;
                            baseVerts = scale * [ 0, 1, 0; -1, -0.5, -0.6; 1, -0.5, -0.6; 0, -0.5, 1 ];
                            baseVerts_matlab = [baseVerts(:,1), baseVerts(:,3), baseVerts(:,2)];
                            faces = [1, 2, 3; 1, 3, 4; 1, 4, 2; 2, 3, 4];
                            
                            % Inject objects into the existing active figure axes
                            hNew.tetPatch = patch('Vertices', baseVerts_matlab, 'Faces', faces, ...
                                'FaceColor', randomColor, 'FaceAlpha', 0.7, 'EdgeColor', 'k');
                            hNew.arrow3D = quiver3(0, 0, 0, 0, 0, 0, 'Color', 'r', 'LineWidth', 2);
                            hNew.trailingPath = animatedline('Color', randomColor, 'LineWidth', 1, 'LineStyle', ':');
                            hNew.baseVertices = baseVerts_matlab;
                            
                            % Store handles mapping to this specific ID
                            activeBodies(rb_id) = hNew;
                        end
                        
                        % Fetch the correct graphic handle for this specific ID and update it
                        hGraphics = activeBodies(rb_id);
                        vis.updateFrame(hGraphics, currentPos, currentQuat);
                        
                        % --- THROTTLED LOGGING ---
                        printCounter = printCounter + 1;
                        if mod(printCounter, 20) == 0
                            fprintf('Active Bodies: %d | Last Updated ID: %d | Z-Height: %6.3f\n', ...
                                activeBodies.Count, rb_id, z_mat);
                        end
                    end
                end
            end
        end
        drawnow limitrate;
        pause(0.001); 
    end
catch ME
    disp('Stream interrupted.');
    disp(ME.message);
end

clear u;
disp('UDP Port safely disconnected.');
