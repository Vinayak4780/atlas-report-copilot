<?php
defined('BASEPATH') OR exit('No direct script access allowed');

/**
 * Thin HTTP client for the Report Copilot API.
 *
 * Never throws: every failure (timeout, connection refused, non-200, malformed JSON) is turned
 * into ['ok' => FALSE, 'error' => <code>, 'message' => <client-safe text>] so the controller can
 * show a clear fallback message instead of a PHP error.
 */
class Atlas_client
{
	const FALLBACK_MESSAGE = 'Sorry, the Report Copilot is unavailable right now. Your question has been saved and passed to a CMR analyst, who will reply by email. No figures have been sent.';

	protected $CI;
	protected $url;
	protected $key;
	protected $timeout;
	protected $connect_timeout;

	public function __construct()
	{
		$this->CI =& get_instance();
		$this->url = $this->CI->config->item('atlas_api_url');
		$this->key = $this->CI->config->item('atlas_api_key');
		$this->timeout = (int) $this->CI->config->item('atlas_api_timeout');
		$this->connect_timeout = (int) $this->CI->config->item('atlas_connect_timeout');
	}

	/**
	 * @param string   $client_id  Client id taken from the server-side session (never from the browser)
	 * @param string   $question
	 * @param string[] $history    Earlier questions in this chat, oldest first
	 * @param string   $session_id
	 * @return array
	 */
	public function ask($client_id, $question, array $history = array(), $session_id = NULL)
	{
		$payload = json_encode(array(
			'client_id'  => $client_id,
			'question'   => $question,
			'history'    => array_values(array_slice($history, -3)),
			'session_id' => $session_id,
		));

		$ch = curl_init($this->url . '/chat');
		curl_setopt_array($ch, array(
			CURLOPT_POST           => TRUE,
			CURLOPT_POSTFIELDS     => $payload,
			CURLOPT_RETURNTRANSFER => TRUE,
			CURLOPT_HTTPHEADER     => array('Content-Type: application/json', 'X-API-Key: ' . $this->key),
			CURLOPT_CONNECTTIMEOUT => $this->connect_timeout,
			CURLOPT_TIMEOUT        => $this->timeout,
		));
		$body = curl_exec($ch);
		$errno = curl_errno($ch);
		$status = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
		curl_close($ch);

		if ($errno === CURLE_OPERATION_TIMEDOUT)
		{
			return $this->_fail('timeout');
		}
		if ($errno !== 0)
		{
			return $this->_fail('unreachable');
		}
		if ($status !== 200)
		{
			return $this->_fail('http_' . $status);
		}
		$data = json_decode($body, TRUE);
		if ( ! is_array($data) OR ! isset($data['answer'], $data['confidence'], $data['citations']))
		{
			return $this->_fail('bad_response');
		}
		return array('ok' => TRUE, 'data' => $data);
	}

	protected function _fail($code)
	{
		log_message('error', 'Atlas API call failed: ' . $code);
		return array('ok' => FALSE, 'error' => $code, 'message' => self::FALLBACK_MESSAGE);
	}
}
