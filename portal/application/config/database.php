<?php
defined('BASEPATH') OR exit('No direct script access allowed');

// Credentials come from the environment (docker-compose -> Apache PassEnv). Nothing secret in git.
$active_group = 'default';
$query_builder = TRUE;

$db['default'] = array(
	'dsn'          => '',
	'hostname'     => getenv('PORTAL_DB_HOST') ?: 'mysql',
	'username'     => getenv('PORTAL_DB_USER') ?: '',
	'password'     => getenv('PORTAL_DB_PASSWORD') ?: '',
	'database'     => getenv('PORTAL_DB_NAME') ?: 'atlas',
	'dbdriver'     => 'mysqli',
	'dbprefix'     => '',
	'pconnect'     => FALSE,
	'db_debug'     => FALSE,
	'cache_on'     => FALSE,
	'cachedir'     => '',
	'char_set'     => 'utf8mb4',
	'dbcollat'     => 'utf8mb4_unicode_ci',
	'swap_pre'     => '',
	'encrypt'      => FALSE,
	'compress'     => FALSE,
	'stricton'     => FALSE,
	'failover'     => array(),
	'save_queries' => FALSE,
);
