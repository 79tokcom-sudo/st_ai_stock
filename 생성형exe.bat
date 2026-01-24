@echo off
echo 천신대왕STAI앱 EXE 생성 시작...
pyinstaller --onefile --windowed --icon=icon.ico --name="천신대왕증권" --add-data "staidb-firebase-adminsdk-fbsvc-d3ba815ea4.json;." --add-data "splash_image_path.json;." 천신대왕_ST_AI_증권_v11.3.py
echo 완료! dist 폴더 확인해주세요~
pause