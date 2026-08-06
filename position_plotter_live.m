if exist('u', 'var')
    clear u;
end

fig = figure('Name', 'OptiTrack Stream', ...
    'NumberTitle', 'off', ...
    'Color', 'w');

grid on;
hold on;
view(3);
axis equal;

xlabel('X Position (m)');
ylabel('Y Position (m)');
zlabel('Vertical Height (m)');

axis([-1 3 -1 3 -0.5 2]);
title('OptiTrack Live');

maxBodies = 100;
trailPoints = 500;

bodyActive = false(maxBodies, 1);
activeBodies = cell(maxBodies, 1);

lastPos  = zeros(maxBodies, 3);
lastQuat = zeros(maxBodies, 4);

frameCounter = zeros(maxBodies, 1);
renderEvery = 3;

u = udpport("LocalPort", 7000, "ByteOrder", "little-endian");
packetBytes = 64;

disp('Listening on Port 7000');

try
    while ishandle(fig)

        didRender = false;

        if u.NumBytesAvailable > 0

            latestBatchUpdates = nan(maxBodies, 8);
            latestValid = false(maxBodies, 1);

            while u.NumBytesAvailable >= packetBytes

                rawBytes = read(u, packetBytes, "uint8");
                vals = typecast(uint8(rawBytes), "double");

                rb_id = round(vals(1));

                if rb_id >= 1 && rb_id <= maxBodies && ~isnan(rb_id)
                    latestBatchUpdates(rb_id, :) = vals;
                    latestValid(rb_id) = true;
                end
            end

            allBatchKeys = find(latestValid);

            for i = 1:length(allBatchKeys)

                rb_id = allBatchKeys(i);
                frameData = latestBatchUpdates(rb_id, :);

                qX   = frameData(2);
                qY   = frameData(3);
                qZ   = frameData(4);
                qW   = frameData(5);
                rawX = frameData(6);
                rawY = frameData(7);
                rawZ = frameData(8);

                x_mat = rawX;
                y_mat = rawZ;
                z_mat = rawY;

                if ~isnan(x_mat) && ~isnan(y_mat) && ~isnan(z_mat) && ...
                   ~isnan(qW) && ~isnan(qX) && ~isnan(qY) && ~isnan(qZ)

                    rawPos  = [x_mat, y_mat, z_mat];
                    rawQuat = [qW, qX, qY, qZ];

                    if ~bodyActive(rb_id)
                        disp(['Detected Rigid Body ID: ', num2str(rb_id)]);

                        randomColor = rand(1, 3);
                        activeBodies{rb_id} = ...
                            createRigidBodyGraphics(randomColor, trailPoints);

                        lastPos(rb_id, :) = rawPos;
                        lastQuat(rb_id, :) = rawQuat;

                        bodyActive(rb_id) = true;
                    end

                    prevPos  = lastPos(rb_id, :);
                    prevQuat = lastQuat(rb_id, :);

                    velocityDistance = norm(rawPos - prevPos);

                    dynamicAlpha = ...
                        0.05 + 0.75 * (1 - exp(-velocityDistance * 35));

                    smoothedPos = ...
                        (dynamicAlpha * rawPos) + ...
                        ((1 - dynamicAlpha) * prevPos);

                    if dot(rawQuat, prevQuat) < 0
                        rawQuat = -rawQuat;
                    end

                    smoothedQuat = ...
                        (dynamicAlpha * rawQuat) + ...
                        ((1 - dynamicAlpha) * prevQuat);

                    smoothedQuat = smoothedQuat / norm(smoothedQuat);

                    lastPos(rb_id, :)  = smoothedPos;
                    lastQuat(rb_id, :) = smoothedQuat;

                    frameCounter(rb_id) = frameCounter(rb_id) + 1;

                    if mod(frameCounter(rb_id), renderEvery) == 0
                        hGraphics = activeBodies{rb_id};

                        updateRigidBodyVisualizer( ...
                            hGraphics, smoothedPos, smoothedQuat);

                        didRender = true;
                    end
                end
            end
        end

        if didRender
            drawnow limitrate;
        end

        pause(0.001);
    end

catch ME
    disp('Stream interrupted.');
    disp(ME.message);
end

clear u;
disp('UDP Port disconnected.');