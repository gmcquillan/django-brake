#!/bin/bash
#PYTHONPATH=.:$PYTHONPATH django-admin.py test brake --settings=test_settings
DJANGO_SETTINGS_MODULE='test_settings' nosetests

