<?php
defined('BASEPATH') OR exit('No direct script access allowed');

/**
 * Conversations and feedback. All queries use the query builder or bound parameters.
 * The portal DB user can read clients.id/company only (never contact_email).
 */
class Conversation_model extends CI_Model
{
	public function list_clients()
	{
		$q = $this->db->select('id, company')->order_by('id')->get('clients');
		return $q ? $q->result_array() : array();
	}

	public function find_client($id)
	{
		$q = $this->db->select('id, company')->where('id', $id)->get('clients');
		$row = $q ? $q->row_array() : NULL;
		return $row ?: NULL;
	}

	public function save(array $row)
	{
		return $this->db->insert('conversations', $row) ? (int) $this->db->insert_id() : NULL;
	}

	public function recent($client_id, $chat_session, $limit = 20)
	{
		$q = $this->db
			->select('c.id, c.question, c.answer, c.confidence, c.escalated, c.status, c.created_at, f.rating')
			->from('conversations c')
			->join('feedback f', 'f.conversation_id = c.id', 'left')
			->where('c.client_id', $client_id)
			->where('c.chat_session', $chat_session)
			->order_by('c.id', 'DESC')
			->limit((int) $limit)
			->get();
		return $q ? array_reverse($q->result_array()) : array();
	}

	public function recent_questions($client_id, $chat_session, $limit = 3)
	{
		$q = $this->db->select('question')
			->where('client_id', $client_id)
			->where('chat_session', $chat_session)
			->where('status', 'ok')
			->order_by('id', 'DESC')
			->limit((int) $limit)
			->get('conversations');
		return $q ? array_reverse(array_column($q->result_array(), 'question')) : array();
	}

	public function owned_by($conversation_id, $client_id)
	{
		$q = $this->db->select('id')
			->where('id', (int) $conversation_id)
			->where('client_id', $client_id)
			->get('conversations');
		return $q && $q->num_rows() === 1;
	}

	public function set_feedback($conversation_id, $rating)
	{
		return $this->db->query(
			'INSERT INTO feedback (conversation_id, rating) VALUES (?, ?) ON DUPLICATE KEY UPDATE rating = VALUES(rating)',
			array((int) $conversation_id, (int) $rating)
		);
	}

	/** Used when the copilot API is down: the question still reaches an analyst. */
	public function create_fallback_ticket($client_id, $question, $reason)
	{
		$ok = $this->db->insert('escalations', array(
			'client_id' => $client_id,
			'question'  => $question,
			'reason'    => 'portal_fallback: ' . $reason,
			'source'    => 'portal_fallback',
		));
		return $ok ? (int) $this->db->insert_id() : NULL;
	}
}
