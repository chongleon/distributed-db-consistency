@echo off
call "%~dp0normal.bat"
echo Simulating node failure: stopping mongo3...
docker stop mongo3
timeout /t 5 >nul
docker exec mongo1 mongosh --quiet --eval "rs.status().members.map(m => ({name:m.name,state:m.stateStr,health:m.health}))"