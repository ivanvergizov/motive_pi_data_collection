function session = loadOptiTrackRigidBodyCSV(fullFilePath, applySmoothing, smoothWindow)

if nargin < 2
    applySmoothing = false;
end

if nargin < 3
    smoothWindow = 121;
end

if ~isfile(fullFilePath)
    error("CSV file not found: %s", fullFilePath);
end

fid = fopen(fullFilePath, 'r');

if fid == -1
    error("Could not open CSV file: %s", fullFilePath);
end

cleanupObj = onCleanup(@() fclose(fid));

header = strings(7, 1);

for i = 1:7
    line = fgetl(fid);

    if ~ischar(line)
        error("Unexpected end of file while reading CSV header.");
    end

    header(i) = string(line);
end

types = split(header(3), ",")';
types = types(3:end);

objectNamesRaw = split(header(4), ",")';
objectNamesRaw = objectNamesRaw(3:end);
objectNamesRaw = objectNamesRaw(objectNamesRaw ~= "");

objectNames = unique(objectNamesRaw, "stable");
objectFields = matlab.lang.makeValidName(objectNames);

transformTypes = split(header(6), ",")';
transformTypes = transformTypes(3:end);

transformDimensions = split(header(7), ",")';
transformDimensions = transformDimensions(3:end);

numericData = readmatrix(fullFilePath, "NumHeaderLines", 7);

numericData = numericData(~all(isnan(numericData), 2), :);

frames = numericData(:, 1);
time = numericData(:, 2);
transformData = numericData(:, 3:end);

dimsPerObject = 7;
expectedColumns = numel(objectNames) * dimsPerObject;

if size(transformData, 2) < expectedColumns
    error( ...
        "Expected at least %d transform columns, but found %d.", ...
        expectedColumns, size(transformData, 2));
end

transformData = transformData(:, 1:expectedColumns);

if applySmoothing
    smoothWindow = min(smoothWindow, size(transformData, 1));

    if mod(smoothWindow, 2) == 0
        smoothWindow = smoothWindow - 1;
    end

    if smoothWindow >= 5
        transformData = fillmissing(transformData, "linear");
        transformData = smoothdata(transformData, 1, "movmedian", smoothWindow);
        transformData = smoothdata(transformData, 1, "sgolay", smoothWindow);
    end
end

session = struct();

session.fullFilePath = fullFilePath;
session.frames = frames;
session.time = time;
session.objectNames = objectNames;
session.objectFields = objectFields;
session.types = types;
session.transformTypes = transformTypes;
session.transformDimensions = transformDimensions;
session.transformData = transformData;
session.dimsPerObject = dimsPerObject;

for i = 1:numel(objectNames)
    field = objectFields(i);
    startIdx = (i - 1) * dimsPerObject + 1;

    session.objects.(field).OriginalName = objectNames(i);

    session.objects.(field).Rotation.X = transformData(:, startIdx);
    session.objects.(field).Rotation.Y = transformData(:, startIdx + 1);
    session.objects.(field).Rotation.Z = transformData(:, startIdx + 2);
    session.objects.(field).Rotation.W = transformData(:, startIdx + 3);

    session.objects.(field).Position.X = transformData(:, startIdx + 4);
    session.objects.(field).Position.Y = transformData(:, startIdx + 5);
    session.objects.(field).Position.Z = transformData(:, startIdx + 6);
end

end