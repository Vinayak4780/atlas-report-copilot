<?php
defined('BASEPATH') OR exit('No direct script access allowed');

// Report Copilot (Python API) connection settings, from the environment.
$config['atlas_api_url'] = rtrim(getenv('ATLAS_API_URL') ?: 'http://api:8000', '/');
$config['atlas_api_key'] = getenv('ATLAS_API_KEY') ?: '';
$config['atlas_api_timeout'] = (int) (getenv('ATLAS_API_TIMEOUT') ?: 32);
$config['atlas_connect_timeout'] = 3;
