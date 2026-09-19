@echo off
call scripts\normal.bat
echo Simulating network partition: isolating mongo3...
docker network disconnect dsa5208p1_default mongo3
timeout /t 5 >nul
docker exec mongo1 mongosh --quiet --eval "rs.status().members.map(m => ({name:m.name,state:m.stateStr,health:m.health}))"