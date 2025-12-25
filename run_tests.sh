#!/bin/bash

# Simple test runner script for gcloud-notion-service

echo "Running tests..."
echo "==============================================="

case "${1:-all}" in
    all)
        python3 -m unittest test_main.py -v
        ;;
    quick)
        python3 -m unittest test_main.py
        ;;
    auth)
        python3 -m unittest test_main.TestAuthentication -v
        ;;
    rate)
        python3 -m unittest test_main.TestRateLimiting -v
        ;;
    notion)
        python3 -m unittest test_main.TestNotionIntegration -v
        ;;
    helpers)
        python3 -m unittest test_main.TestHelperFunctions -v
        ;;
    coverage)
        echo "Installing coverage if needed..."
        pip3 install coverage -q
        coverage run -m unittest test_main.py
        echo ""
        coverage report
        ;;
    *)
        echo "Usage: ./run_tests.sh [all|quick|auth|rate|notion|helpers|coverage]"
        exit 1
        ;;
esac
