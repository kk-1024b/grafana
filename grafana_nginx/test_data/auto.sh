#!/bin/bash
# 循环 100 次 curl 到地址 a
for ll in {01..30}; do
   file_time="2025-10-${ll}_10-14-21"
   echo "${file_time}"
   curl -u user:pass123 -T /home/kk/catch2_data/pywatcher/data/testResult.csv http://localhost:9699/details/sources/${file_time}/testResult.csv
   sleep 1
done
