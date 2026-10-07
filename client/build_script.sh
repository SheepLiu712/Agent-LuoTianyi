#!/bin/bash

# Resolve every path relative to this script, not the caller's working directory.
cd -- "$(dirname -- "${BASH_SOURCE[0]}")" || exit 1
mkdir -p logs || exit 1
LOG_FILE="logs/build_log.txt"
exec > >(tee -a "$LOG_FILE") 2>&1

APP_NAME="AgentLuoChat"


while true; do
    read -r -p "Build type (Release/Debug): " BUILD_TYPE || exit 1
    case "${BUILD_TYPE,,}" in
        release) BUILD_TYPE="Release"; break ;;
        debug) BUILD_TYPE="Debug"; break ;;
        *) echo "Please enter Release or Debug." ;;
    esac
done

while true; do
    read -r -p "Version (e.g. 0.4.0): " VERSION || exit 1
    if [[ "$VERSION" =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]]; then
        break
    fi
    echo "Invalid version. Use three numbers separated by dots, e.g. 0.4.0."
done

# PyInstaller appends the app name to --distpath, so the onedir bundle lands one level below BUILD_ROOT.
BUILD_ROOT="bin/$APP_NAME-$BUILD_TYPE-$VERSION"
BUILD_FOLDER="$BUILD_ROOT/$APP_NAME"
WORK_FOLDER="build/$APP_NAME-$BUILD_TYPE-$VERSION"
TARGET_FOLDER="dist/$APP_NAME-$BUILD_TYPE-$VERSION"
if [ -e "$TARGET_FOLDER" ]; then
    echo "Error: '$TARGET_FOLDER' already exists. Move it away before rebuilding this version."
    exit 1
fi
for folder in config res; do
    if [ ! -d "$folder" ]; then
        echo "Error: Required folder '$folder' does not exist."
        exit 1
    fi
done

echo "Building $APP_NAME ($BUILD_TYPE $VERSION) at $(date)"
echo "Activating Conda environment 'lty_c'..."
source D:/Anaconda/etc/profile.d/conda.sh || exit 1
conda activate lty_c || exit 1

BUILD_OPTIONS=()
if [ "$BUILD_TYPE" = "Debug" ]; then
    BUILD_OPTIONS+=(--debug=all)
fi

pyinstaller -i res/gui/icon.ico -n "$APP_NAME" -D -y main.py \
    --distpath "$BUILD_ROOT" \
    --workpath "$WORK_FOLDER" \
    --add-data="D:\Anaconda\envs\lty_c\lib\site-packages\live2d;live2d" \
    "${BUILD_OPTIONS[@]}"
if [ $? -ne 0 ]; then
    echo "PyInstaller command failed. Exiting."
    exit 1
fi

if [ ! -d "$BUILD_FOLDER/_internal" ] || [ ! -f "$BUILD_FOLDER/$APP_NAME.exe" ]; then
    echo "Error: PyInstaller output in '$BUILD_FOLDER' is incomplete."
    exit 1
fi

mkdir -p "$TARGET_FOLDER" || exit 1
cp -r "$BUILD_FOLDER/_internal" "$TARGET_FOLDER/" || exit 1
cp "$BUILD_FOLDER/$APP_NAME.exe" "$TARGET_FOLDER/" || exit 1
cp -r config res "$TARGET_FOLDER/" || exit 1

echo "Build completed: $TARGET_FOLDER/$APP_NAME.exe"
echo "Script finished at: $(date)"
