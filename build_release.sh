#!/bin/bash

Tools/Scripts/build-webkit --release --only=WebKit \
    COMPILATION_CACHE_ENABLE_CACHING=NO \
    CLANG_ENABLE_COMPILE_CACHE=NO \
    2>&1 | tee build-release.log
