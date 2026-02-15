@echo off
chcp 65001 >nul
title 漫画下载器 - Manga Downloader
cd /d "%~dp0"
start "" pythonw app.py
