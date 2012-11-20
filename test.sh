#!/bin/bash
PYTHONPATH=.:$PYTHONPATH django-admin.py test brake --settings=test_settings

