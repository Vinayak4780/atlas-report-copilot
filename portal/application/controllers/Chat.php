<?php
defined('BASEPATH') OR exit('No direct script access allowed');

/**
 * Report Copilot chat inside the CI3 portal.
 *
 *   GET  /chat            chat page (requires a signed-in client)
 *   GET  /chat/login      demo sign-in (stands in for the portal's existing authentication)
 *   POST /chat/login
 *   POST /chat/logout
 *   POST /chat/ask        AJAX, CSRF-protected; calls the Python API via Atlas_client
 *   POST /chat/feedback   AJAX, CSRF-protected; thumbs up/down
 *
 * The client_id sent to the API always comes from the server-side session, never from the browser.
 */
class Chat extends CI_Controller
{
	const MAX_QUESTION_LENGTH = 1000;

	public function __construct()
	{
		parent::__construct();
		$this->load->model('conversation_model');
		$this->load->library('atlas_client');
	}

	public function index()
	{
		$client = $this->_client();
		if ($client === NULL)
		{
			redirect('chat/login');
			return;
		}
		$this->load->view('chat/index', array(
			'client'  => $client,
			'history' => $this->conversation_model->recent($client['id'], $this->session->userdata('chat_session')),
		));
	}

	public function login()
	{
		$data = array('error' => NULL, 'clients' => $this->conversation_model->list_clients());
		if ($this->input->method() === 'post')
		{
			$id = (string) $this->input->post('client_id');
			$client = preg_match('/^C-\d{2,4}$/', $id) ? $this->conversation_model->find_client($id) : NULL;
			if ($client)
			{
				$this->session->sess_regenerate(TRUE);
				$this->session->set_userdata(array(
					'client'       => $client,
					'chat_session' => bin2hex(random_bytes(16)),
				));
				redirect('chat');
				return;
			}
			$data['error'] = 'Please choose a valid client account.';
		}
		$this->load->view('chat/login', $data);
	}

	public function logout()
	{
		if ($this->input->method() !== 'post')
		{
			show_error('Method not allowed', 405);
			return;
		}
		$this->session->sess_destroy();
		redirect('chat/login');
	}

	public function ask()
	{
		if ($this->input->method() !== 'post')
		{
			$this->_json(array('ok' => FALSE, 'error' => 'Method not allowed'), 405);
			return;
		}
		$client = $this->_client();
		if ($client === NULL)
		{
			$this->_json(array('ok' => FALSE, 'error' => 'Your session has expired. Please sign in again.'), 401);
			return;
		}
		$question = trim((string) $this->input->post('question'));
		if ($question === '' OR mb_strlen($question) > self::MAX_QUESTION_LENGTH)
		{
			$this->_json(array('ok' => FALSE, 'error' => 'Please enter a question of up to 1000 characters.'), 422);
			return;
		}

		$chat_session = $this->session->userdata('chat_session');
		$history = $this->conversation_model->recent_questions($client['id'], $chat_session, 3);
		$result = $this->atlas_client->ask($client['id'], $question, $history, $chat_session);

		if ($result['ok'])
		{
			$resp = $result['data'];
			$conversation_id = $this->conversation_model->save(array(
				'client_id'     => $client['id'],
				'chat_session'  => $chat_session,
				'question'      => $question,
				'answer'        => (string) $resp['answer'],
				'response_json' => json_encode($resp),
				'confidence'    => (float) $resp['confidence'],
				'escalated'     => ! empty($resp['escalated']) ? 1 : 0,
				'status'        => 'ok',
				'request_id'    => isset($resp['request_id']) ? $resp['request_id'] : NULL,
			));
			$this->_json(array('ok' => TRUE, 'conversation_id' => $conversation_id, 'response' => $resp));
			return;
		}

		// Graceful fallback: save the question, open a ticket from the portal side, show a clear message.
		$ticket = $this->conversation_model->create_fallback_ticket($client['id'], $question, $result['error']);
		$message = $result['message'] . ($ticket ? ' Reference: ticket #' . $ticket . '.' : '');
		$conversation_id = $this->conversation_model->save(array(
			'client_id'    => $client['id'],
			'chat_session' => $chat_session,
			'question'     => $question,
			'answer'       => $message,
			'status'       => 'fallback',
			'escalated'    => $ticket ? 1 : 0,
		));
		$this->_json(array('ok' => FALSE, 'fallback' => TRUE, 'conversation_id' => $conversation_id,
			'message' => $message));
	}

	public function feedback()
	{
		$client = $this->_client();
		if ($this->input->method() !== 'post' OR $client === NULL)
		{
			$this->_json(array('ok' => FALSE, 'error' => 'Not allowed'), 403);
			return;
		}
		$conversation_id = (int) $this->input->post('conversation_id');
		$rating = (int) $this->input->post('rating');
		if ( ! in_array($rating, array(1, -1), TRUE) OR ! $this->conversation_model->owned_by($conversation_id, $client['id']))
		{
			$this->_json(array('ok' => FALSE, 'error' => 'Invalid feedback'), 422);
			return;
		}
		$this->conversation_model->set_feedback($conversation_id, $rating);
		$this->_json(array('ok' => TRUE));
	}

	private function _client()
	{
		$client = $this->session->userdata('client');
		return is_array($client) ? $client : NULL;
	}

	private function _json(array $data, $status = 200)
	{
		$this->output
			->set_status_header($status)
			->set_content_type('application/json', 'utf-8')
			->set_output(json_encode($data, JSON_HEX_TAG | JSON_HEX_AMP | JSON_HEX_APOS | JSON_HEX_QUOT));
	}
}
