@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在把插件安装到 DSH 的 desktop profile…
dsh plugin --profile desktop add "file:%~dp0plugin"
if errorlevel 1 (
  echo.
  echo 安装失败。请确认 dsh 已加入 PATH，或手动执行：
  echo   dsh plugin --profile desktop add "file:%~dp0plugin"
  pause
  exit /b 1
)
echo.
echo 安装完成。还需要在下面这个文件里追加两行，然后重启 DSH：
echo   %%USERPROFILE%%\.dsh\profiles\desktop\cordis.patch.yml
echo.
echo   - id: hnu-class-ppt
echo     name: dsh-hnu-class-ppt
echo.
pause
