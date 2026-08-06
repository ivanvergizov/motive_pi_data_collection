clc;
clear;

%% File settings

filename = "test2.csv";
folder = "TestSession";
fullFilePath = fullfile(folder, filename);

outputFolder = "RenderedVideos";
outputName = "optiTrack_render.mp4";
outputPath = fullfile(outputFolder, outputName);

if ~isfolder(outputFolder)
    mkdir(outputFolder);
end

%% Render settings

applySmoothing = true;
smoothWindow = 121;

objectsToRender = "all";   % use "all" or ["TestRigid1", "OtherBody"]
stepSize = 1;              % 1 = every frame, 2 = every other frame
videoFrameRate = 30;
videoQuality = 95;

figureWidth = 3840;
figureHeight = 1600;

trailDurationSeconds = 10;
trailPoints = inf; % round(trailDurationSeconds * videoFrameRate) or inf

pad = 0.2;

%% Load data

session = loadOptiTrackRigidBodyCSV( ...
    fullFilePath, ...
    applySmoothing, ...
    smoothWindow);

objectNames = session.objectNames;
objectFields = session.objectFields;

if objectsToRender == "all"
    selectedFields = objectFields;
    selectedNames = objectNames;
else
    selectedNames = objectsToRender;
    selectedFields = matlab.lang.makeValidName(selectedNames);
end

numBodies = numel(selectedFields);

if numBodies == 0
    error("No rigid bodies selected.");
end

%% Compute global display limits

minX = inf;  maxX = -inf;
minY = inf;  maxY = -inf;
minZ = inf;  maxZ = -inf;

for i = 1:numBodies
    field = selectedFields(i);

    if ~isfield(session.objects, field)
        error("Object not found in CSV: %s", selectedNames(i));
    end

    obj = session.objects.(field);

    X = obj.Position.X;
    Y = obj.Position.Z;
    Z = obj.Position.Y;

    valid = isfinite(X) & isfinite(Y) & isfinite(Z);

    if any(valid)
        minX = min(minX, min(X(valid)));
        maxX = max(maxX, max(X(valid)));

        minY = min(minY, min(Y(valid)));
        maxY = max(maxY, max(Y(valid)));

        minZ = min(minZ, min(Z(valid)));
        maxZ = max(maxZ, max(Z(valid)));
    end
end

if any(~isfinite([minX, maxX, minY, maxY, minZ, maxZ]))
    error("No finite position samples found for selected objects.");
end

limits = [
    minX-pad, maxX+pad, ...
    minY-pad, maxY+pad, ...
    minZ-pad, maxZ+pad
];

%% Setup figure

fig = figure( ...
    "Name", "OptiTrack CSV Render", ...
    "NumberTitle", "off", ...
    "Color", "w", ...
    "Position", [100, 100, figureWidth, figureHeight]);

grid on;
hold on;
view(3);
axis equal;
axis(limits);

xlabel("X Position (m)");
ylabel("Y Position (m)");
zlabel("Vertical Height (m)");
title("OptiTrack CSV Render");

%% Create graphics objects

colors = lines(numBodies);
hBodies = cell(numBodies, 1);

for i = 1:numBodies
    hBodies{i} = createRigidBodyGraphics(colors(i, :), trailPoints);
end

%% Precompute timestamp-based render samples

dataTime = session.time;
dataTime = dataTime - dataTime(1);

videoTimes = 0 : 1/videoFrameRate : dataTime(end);

dataIndexForVideoFrame = interp1( ...
    dataTime, ...
    1:numel(dataTime), ...
    videoTimes, ...
    "nearest", ...
    "extrap");

dataIndexForVideoFrame = round(dataIndexForVideoFrame);
dataIndexForVideoFrame = ...
    max(1, min(numel(dataTime), dataIndexForVideoFrame));

numVideoFrames = numel(videoTimes);

renderData = cell(numBodies, 1);

for i = 1:numBodies
    field = selectedFields(i);
    obj = session.objects.(field);

    renderData{i}.Position = [
        interp1(dataTime, obj.Position.X, videoTimes, "linear", "extrap").', ...
        interp1(dataTime, obj.Position.Z, videoTimes, "linear", "extrap").', ...
        interp1(dataTime, obj.Position.Y, videoTimes, "linear", "extrap").'
        ];

    renderData{i}.Quat = [
        obj.Rotation.W(dataIndexForVideoFrame), ...
        obj.Rotation.X(dataIndexForVideoFrame), ...
        obj.Rotation.Y(dataIndexForVideoFrame), ...
        obj.Rotation.Z(dataIndexForVideoFrame)
        ];
end

fprintf("Data duration: %.3f seconds\n", dataTime(end));
fprintf("Video frame rate: %.2f fps\n", videoFrameRate);
fprintf("Video frames to write: %d\n", numVideoFrames);
fprintf("Expected video duration: %.3f seconds\n", numVideoFrames / videoFrameRate);

%% Setup video writer

v = VideoWriter(outputPath, "MPEG-4");
v.FrameRate = videoFrameRate;
v.Quality = videoQuality;
open(v);

%% Render loop

for vf = 1:numVideoFrames

    for i = 1:numBodies
        currentPos = renderData{i}.Position(vf, :);
        currentQuat = renderData{i}.Quat(vf, :);

        if all(isfinite(currentPos)) && all(isfinite(currentQuat))
            updateRigidBodyVisualizer( ...
                hBodies{i}, ...
                currentPos, ...
                currentQuat);
        end
    end

    drawnow;

    frame = getframe(fig);
    img = frame.cdata;
    
    img = imresize(img, [figureHeight, figureWidth]);
    
    img = makeFrameEvenSize(img);
    
    writeVideo(v, img);
end

close(v);

disp("Saved video:");
disp(outputPath);

function img = makeFrameEvenSize(img)

[h, w, ~] = size(img);

if mod(h, 2) ~= 0
    img = img(1:end-1, :, :);
end

if mod(w, 2) ~= 0
    img = img(:, 1:end-1, :);
end

end