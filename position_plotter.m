clc;
clear;

filename = "test2.csv";
folder = "TestSession";
fullFilePath = fullfile(folder, filename);

applySmoothing = true;
smoothWindow = 121;
trailPoints = 2000;

session = loadOptiTrackRigidBodyCSV( ...
    fullFilePath, ...
    applySmoothing, ...
    smoothWindow);

disp("Loaded objects:");
disp(session.objectNames.');

targetObj = "TestRigid1";
targetField = matlab.lang.makeValidName(targetObj);

if ~isfield(session.objects, targetField)
    error("Object not found: %s", targetObj);
end

obj = session.objects.(targetField);
time = session.time;

figure;
plot(time, obj.Rotation.X);
title(targetObj + " Rotation X");
xlabel("Time");
ylabel("Rotation X");

figure;
plot(time, obj.Rotation.Y);
title(targetObj + " Rotation Y");
xlabel("Time");
ylabel("Rotation Y");

figure;
plot(time, obj.Rotation.Z);
title(targetObj + " Rotation Z");
xlabel("Time");
ylabel("Rotation Z");

figure;
plot(time, obj.Rotation.W);
title(targetObj + " Rotation W");
xlabel("Time");
ylabel("Rotation W");

figure;
plot(time, obj.Position.X);
title(targetObj + " Position X");
xlabel("Time");
ylabel("Position X");

figure;
plot(time, obj.Position.Y);
title(targetObj + " Position Y");
xlabel("Time");
ylabel("Position Y");

figure;
plot(time, obj.Position.Z);
title(targetObj + " Position Z");
xlabel("Time");
ylabel("Position Z");

%% Quick animation

X_mat = obj.Position.X;
Y_mat = obj.Position.Z;
Z_mat = obj.Position.Y;

qX = obj.Rotation.X;
qY = obj.Rotation.Y;
qZ = obj.Rotation.Z;
qW = obj.Rotation.W;

pad = 0.2;

limits = [
    min(X_mat)-pad, max(X_mat)+pad, ...
    min(Y_mat)-pad, max(Y_mat)+pad, ...
    min(Z_mat)-pad, max(Z_mat)+pad
];

hGraphics = RigidBodyVisualizer(limits, trailPoints);
title("Tracking " + targetObj);

stepSize = 5;
playbackSpeed = 1.0;

previewTime = session.time;
previewTime = previewTime - previewTime(1);

playbackTimer = tic;

for k = 1:stepSize:length(X_mat)

    targetWallTime = previewTime(k) / playbackSpeed;

    while toc(playbackTimer) < targetWallTime
        pause(0.001);
    end

    currentPos = [X_mat(k), Y_mat(k), Z_mat(k)];
    currentQuat = [qW(k), qX(k), qY(k), qZ(k)];

    if all(isfinite(currentPos)) && all(isfinite(currentQuat))
        updateRigidBodyVisualizer(hGraphics, currentPos, currentQuat);
        drawnow limitrate;
    end
end