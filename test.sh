#!/bin/bash
PYTHONPATH=.:$PYTHONPATH manage.py test --settings=test_settings brake

