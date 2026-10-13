#!/bin/sh
set -e
pyinstaller --noconfirm --clean --name ImageRater gui.py
rm -rf ImageRater.AppDir/usr/bin/*
cp -r dist/ImageRater/* ImageRater.AppDir/usr/bin/
ARCH=x86_64 appimagetool ImageRater.AppDir ImageRater-x86_64.AppImage
