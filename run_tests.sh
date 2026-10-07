#!/bin/bash
# Roda os testes ignorando plugins instalados no sistema (conflito com o ROS 2).
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest "$@"
