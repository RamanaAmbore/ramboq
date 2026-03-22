#!/bin/bash

LOG="/opt/ramboq/.log/incoming_requests.log"
TS=$(date '+%Y-%m-%d %H:%M:%S')

{
  echo "[$TS] Incoming webhook request"
  echo "  QUERY_STRING: ${QUERY_STRING}"
  echo "  REQUEST_METHOD: ${REQUEST_METHOD}"
} >> "$LOG" 2>&1
