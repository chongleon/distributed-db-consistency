@echo off
docker start mongo1 mongo2 mongo3
docker network connect dsa5208p1_default mongo3 2>nul
echo Waiting for replica set to recover...
timeout /t 10 >nul
docker exec mongo1 mongosh --quiet --eval "rs.status().members.map(m => ({name:m.name,state:m.stateStr,health:m.health}))"