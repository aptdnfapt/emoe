#!/bin/bash

docker-compose up -d ollama

docker exec -it ollama_service ollama pull hf.co/mradermacher/DialoGPT-large-gavin-GGUF:F16

docker-compose up -d
