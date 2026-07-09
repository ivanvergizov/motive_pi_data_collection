if exist('u', 'var')
    clear u;
end

% Initialize Visualizer Engine
vis = RigidBodyVisualizer();

% Setup a master figure environment
fig = figure('Name', 'OptiTrack Multi-Body Ultra-Stream', 'NumberTitle', 'off', 'Color', 'w');
grid on; hold on; view(3); axis equal;
xlabel('X Position (m)'); ylabel('Y Position (m)'); zlabel('Vertical Height (m)');

% --- ACCURATE ROOM SIZE ADJUSTMENT ---
axis([-1 3 -1 3 -0.5 2]); 
title('Live Multi-Rigid Body Tracking (Adaptive Filter)');

% Create dynamic tracking maps
activeBodies   = containers.Map('KeyType', 'double', 'ValueType', 'any');
historyBodies  = containers.Map('KeyType', 'double', 'ValueType', 'any');

% Open Port 7000
u = udpport("LocalPort", 7000); 
configureTerminator(u, "LF"); 

disp('Listening on Port 7000. Adaptive dynamic smoothing active.');
clc;

try
    while ishandle(fig)
        
        bytesAvail = u.NumBytesAvailable;
        if bytesAvail > 0
            
            latestBatchUpdates = containers.Map('KeyType', 'double', 'ValueType', 'any');
            
            % Drain network buffer queue
            while u.NumBytesAvailable > 0
                raw_data = readline(u);
                if raw_data == "", continue; end
                
                split_data = split(strip(raw_data), ",");
                if length(split_data) >= 8
                    rb_id = double(split_data(1));
                    latestBatchUpdates(rb_id) = split_data(1:8); 
                end
            end
            
            % Process batch allocations
            allBatchKeys = keys(latestBatchUpdates);
            for i = 1:length(allBatchKeys)
                currentKey = allBatchKeys{i};
                frameData = latestBatchUpdates(currentKey);
                
                rb_id = double(frameData(1));
                qX    = double(frameData(2));
                qY    = double(frameData(3));
                qZ    = double(frameData(4));
                qW    = double(frameData(5));
                rawX  = double(frameData(6));
                rawY  = double(frameData(7));
                rawZ  = double(frameData(8));
                
                % Workspace axis remapping (Motive Y-up to MATLAB Z-up)
                x_mat = rawX;
                y_mat = rawZ; 
                z_mat = rawY; 
                
                if ~isnan(rb_id) && ~isnan(x_mat) && ~isnan(y_mat) && ~isnan(z_mat) && ...
                   ~isnan(qW) && ~isnan(qX) && ~isnan(qY) && ~isnan(qZ)
                    
                    rawPos  = [x_mat, y_mat, z_mat];
                    rawQuat = [qW, qX, qY, qZ];
                    
                    % Dynamic object enrollment
                    if ~isKey(activeBodies, rb_id)
                        disp(['Detected new Rigid Body ID: ', num2str(rb_id)]);
                        randomColor = rand(1, 3); 
                        
                        scale = 0.15;
                        baseVerts = scale * [0, 1, 0; -1, -0.5, -0.6; 1, -0.5, -0.6; 0, -0.5, 1];
                        baseVerts_matlab = [baseVerts(:,1), baseVerts(:,3), baseVerts(:,2)];
                        faces = [1, 2, 3; 1, 3, 4; 1, 4, 2; 2, 3, 4];
                        
                        hNew.tetPatch = patch('Vertices', baseVerts_matlab, 'Faces', faces, ...
                            'FaceColor', randomColor, 'FaceAlpha', 0.7, 'EdgeColor', 'k');
                        hNew.arrow3D = quiver3(0, 0, 0, 0, 0, 0, 'Color', 'r', 'LineWidth', 2);
                        hNew.trailingPath = animatedline('Color', randomColor, 'LineWidth', 1, 'LineStyle', ':');
                        hNew.baseVertices = baseVerts_matlab;
                        
                        activeBodies(rb_id) = hNew;
                        
                        hState.lastPos  = rawPos;
                        hState.lastQuat = rawQuat;
                        historyBodies(rb_id) = hState;
                    end
                    
                    % --- ADAPTIVE FILTER MATH ---
                    state = historyBodies(rb_id);
                    
                    % Calculate physical velocity step distance since last frame
                    velocityDistance = norm(rawPos - state.lastPos);
                    
                    % Compute dynamic smoothing factor based on velocity
                    % If moving fast, alpha climbs toward 0.8 (low filter, zero lag)
                    % If staying still, alpha drops toward 0.05 (heavy filter)
                    dynamicAlpha = 0.05 + 0.75 * (1 - exp(-velocityDistance * 35));
                    
                    % Smooth position coordinates
                    smoothedPos = (dynamicAlpha * rawPos) + ((1 - dynamicAlpha) * state.lastPos);
                    
                    % Coordinate sign-flipping neighborhood ambiguities for quaternions
                    if dot(rawQuat, state.lastQuat) < 0
                        rawQuat = -rawQuat;
                    end
                    smoothedQuat = (dynamicAlpha * rawQuat) + ((1 - dynamicAlpha) * state.lastQuat);
                    smoothedQuat = smoothedQuat / norm(smoothedQuat);
                    
                    % Save state back to history container
                    state.lastPos  = smoothedPos;
                    state.lastQuat = smoothedQuat;
                    historyBodies(rb_id) = state;
                    
                    % Render scene update frame
                    hGraphics = activeBodies(rb_id);
                    vis.updateFrame(hGraphics, smoothedPos, smoothedQuat);
                end
            end
        end
        
        drawnow; 
        pause(0.001); 
    end
catch ME
    disp('Stream interrupted.');
    disp(ME.message);
end

clear u;
disp('UDP Port safely disconnected.');
