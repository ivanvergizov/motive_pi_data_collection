clc, clear

% assumes rigid bodies only with 7 dimensions per body

filename = "test2.csv";
folder = "TestSession";
fullFilePath = fullfile(folder, filename);

csvData = fopen(fullFilePath, 'r');
trackingSession = struct();

for i = 1:2
    fgetl(csvData);
end

types = split((fgetl(csvData)), ',')';
types = types(3:end);

object_names = split((fgetl(csvData)), ',')';
object_names = unique(object_names(3:end), 'stable');

fgetl(csvData);

transform_types = split((fgetl(csvData)), ',')';
transform_types = transform_types(3:end);

transform_dimensions = split((fgetl(csvData)), ',')';
transform_dimensions = transform_dimensions(3:end);

fclose(csvData);

dataTable = readtable(fullFilePath);
data = dataTable(5:end,:);

frames = table2array(data(:, 1));
time = table2array(data(:, 2));

transform_data = table2array(data(:, 3:end));

trackingSession.frames = frames;
trackingSession.time = time;

smooth_window = 121;

filled = fillmissing(transform_data, 'linear');
median = smoothdata(filled, 1, 'movmedian', smooth_window);
smooth = smoothdata(median, 1, 'sgolay', smooth_window);
transform_data = smooth;

for i = 1:length(object_names)
    object = char(object_names(i));

    dimsPerObject = 7; % Assuming 7 dimensions per object
    % Dynamically calculate the column chunk for this specific object
    startIdx = (i-1) * dimsPerObject + 1;

    trackingSession.(object) = struct();
    trackingSession.(object).Rotation.X = transform_data(:,startIdx);
    trackingSession.(object).Rotation.Y = transform_data(:,startIdx + 1);
    trackingSession.(object).Rotation.Z = transform_data(:,startIdx + 2);
    trackingSession.(object).Rotation.W = transform_data(:,startIdx + 3);
    trackingSession.(object).Position.X = transform_data(:,startIdx + 4);
    trackingSession.(object).Position.Y = transform_data(:,startIdx + 5);
    trackingSession.(object).Position.Z = transform_data(:,startIdx + 6);
end

time = trackingSession.time;
figure
plot(time, trackingSession.TestRigid1.Rotation.X)
title('Rotation X')

figure
plot(time, trackingSession.TestRigid1.Rotation.Y)
title('Rotation Y')

figure
plot(time, trackingSession.TestRigid1.Rotation.Z)
title('Rotation Z')

figure
plot(time, trackingSession.TestRigid1.Rotation.W)
title('Rotation W')

figure
plot(time, trackingSession.TestRigid1.Position.X)
title('Position X')

figure
plot(time, trackingSession.TestRigid1.Position.Y)
title('Position Y')

figure
plot(time, trackingSession.TestRigid1.Position.Z)
title('Position Z')



%% Animation
targetObj = 'TestRigid1';

% Correct Coordinate Mapping (Motive Y is Vertical Height)
X_mat = trackingSession.(targetObj).Position.X;
Y_mat = trackingSession.(targetObj).Position.Z; % Swap Motive Z to MATLAB Y
Z_mat = trackingSession.(targetObj).Position.Y; % Swap Motive Y (height) to MATLAB Z

% Pull Quaternions
qX = trackingSession.(targetObj).Rotation.X;
qY = trackingSession.(targetObj).Rotation.Y;
qZ = trackingSession.(targetObj).Rotation.Z;
qW = trackingSession.(targetObj).Rotation.W;

% Calculate Boundaries for Offline Display
pad = 0.2;
limits = [min(X_mat)-pad, max(X_mat)+pad, ...
          min(Y_mat)-pad, max(Y_mat)+pad, ...
          min(Z_mat)-pad, max(Z_mat)+pad];

hGraphics = RigidBodyVisualizer(limits);
title(['Tracking ', targetObj]);

% Playback Loop
stepSize = 5;
for k = 1:stepSize:length(X_mat)
    currentPos = [X_mat(k), Y_mat(k), Z_mat(k)];
    currentQuat = [qW(k), qX(k), qY(k), qZ(k)];
    
    % Update scene via helper
    updateRigidBodyVisualizer(hGraphics, currentPos, currentQuat);
    pause(0.01);
end
