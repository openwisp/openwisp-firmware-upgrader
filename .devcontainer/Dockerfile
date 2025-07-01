# Use the official Python image.
FROM mcr.microsoft.com/devcontainers/python:3.11

# Install system dependencies (if you need more, add here)
RUN sudo apt update \
    && sudo apt -qq install -y \
                       sqlite3 \
                       gdal-bin \
                       libproj-dev \
                       libgeos-dev \
                       libspatialite-dev \
                       spatialite-bin \
                       libsqlite3-mod-spatialite \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /workspace

