#!/bin/bash

# Set the log file
LOG_FILE="log.txt"
exec > >(tee -a "$LOG_FILE") 2>&1  # Redirect both stdout and stderr to log.txt

# Log start time
echo "==============================="
echo "Script started at: $(date)"
echo "==============================="

# Activate the Conda environment
echo "Activating Conda environment 'lty_c'..."
source D:/Anaconda/etc/profile.d/conda.sh  # Adjust the path if necessary
conda activate lty_c

if [ $? -ne 0 ]; then
    echo "Failed to activate Conda environment. Exiting."
    exit 1
fi

# Empty the target folder in the parent directory
TARGET_FOLDER="./bin"
echo "Clearing contents of '$TARGET_FOLDER'..."

if [ -d "$TARGET_FOLDER" ]; then
    rm -rf "$TARGET_FOLDER"/*
    echo "Contents of '$TARGET_FOLDER' have been removed."
else
    echo "Error: Folder '$TARGET_FOLDER' does not exist. Creating it..."
    mkdir -p "$TARGET_FOLDER"
fi

# Run the PyInstaller command with the -y option to force output directory removal
echo "Running PyInstaller..."
# pyinstaller -i res/app_icon.ico -n "Tac3D Desktop" -D -y Tac3D_Desktop.py
pyinstaller -i res/gui/icon.ico -n "Chat with Luotianyi" -D -y main.py --add-data="D:\Anaconda\envs\lty_c\lib\site-packages\live2d;live2d"

# Check if the PyInstaller command was successful
if [ $? -ne 0 ]; then
    echo "PyInstaller command failed. Exiting."
    exit 1
fi

# Define the source folder
DIST_FOLDER="dist/Chat with Luotianyi"

# Verify that the source folder exists
if [ ! -d "$DIST_FOLDER" ]; then
    echo "Error: '$DIST_FOLDER' does not exist. Exiting."
    exit 1
fi

# Copy required files and folders to the target folder
echo "Copying files and folders to '$TARGET_FOLDER'..."

echo "  Copying _internal folder..."
cp -r "$DIST_FOLDER/_internal" "$TARGET_FOLDER/"
if [ $? -eq 0 ]; then
    echo "  ✓ _internal copied successfully"
else
    echo "  ✗ Failed to copy _internal"
fi

echo "  Copying executable..."
cp "$DIST_FOLDER/Chat with Luotianyi.exe" "$TARGET_FOLDER/"
if [ $? -eq 0 ]; then
    echo "  ✓ Executable copied successfully"
else
    echo "  ✗ Failed to copy executable"
fi

# Copy config and res folders if they exist
echo "  Checking for config folder..."
if [ -d "config" ]; then
    echo "  Found config folder, copying..."
    cp -r "config" "$DIST_FOLDER/"
    if [ $? -eq 0 ]; then
        echo "  ✓ config folder copied successfully"
    else
        echo "  ✗ Failed to copy config folder"
    fi
else
    echo "  ✗ config folder not found in current directory"
fi

echo "  Checking for res folder..."
if [ -d "res" ]; then
    echo "  Found res folder, copying..."
    cp -r "res" "$DIST_FOLDER/"
    if [ $? -eq 0 ]; then
        echo "  ✓ res folder copied successfully"
    else
        echo "  ✗ Failed to copy res folder"
    fi
else
    echo "  ✗ res folder not found in current directory"
fi

echo "  Checking for temp folder..."
if [ id "temp"]; then
    echo "  Found temp folder, copying..."
    cp -r "temp" "$DIST_FOLDER/"
    if [ $? -eq 0 ]; then
        echo "  ✓ temp folder copied successfully"
    else
        echo "  ✗ Failed to copy temp folder"
    fi
fi

echo "Copy operations completed."

# Log completion time
echo "==============================="
echo "Script finished at: $(date)"
echo "==============================="
