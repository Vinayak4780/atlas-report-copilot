<?php
defined('BASEPATH') OR exit('No direct script access allowed');

/*
 * Production overrides, loaded by CodeIgniter after config/config.php (CI_ENV=production).
 * Only the keys that differ from the stock CI3 config are set here.
 */
$config['base_url'] = rtrim(getenv('PORTAL_BASE_URL') ?: 'http://localhost:8080', '/') . '/';
$config['index_page'] = 'index.php';
$config['log_threshold'] = 1;

// Sessions: server-side files, HttpOnly + SameSite cookies, id regenerated at sign-in.
$config['sess_driver'] = 'files';
$config['sess_cookie_name'] = 'atlas_session';
$config['sess_save_path'] = '/var/www/sessions';
$config['sess_expiration'] = 7200;
$config['sess_match_ip'] = FALSE;
$config['sess_time_to_update'] = 300;
$config['sess_regenerate_destroy'] = TRUE;
$config['cookie_httponly'] = TRUE;
$config['cookie_samesite'] = 'Lax';

// CSRF protection on every POST (token is sent by the chat page with each AJAX request).
$config['csrf_protection'] = TRUE;
$config['csrf_token_name'] = 'atlas_csrf';
$config['csrf_cookie_name'] = 'atlas_csrf_cookie';
$config['csrf_expire'] = 7200;
$config['csrf_regenerate'] = FALSE;
$config['csrf_exclude_uris'] = array();

// Output is escaped in the views (html_escape / textContent); input is not mangled.
$config['global_xss_filtering'] = FALSE;
