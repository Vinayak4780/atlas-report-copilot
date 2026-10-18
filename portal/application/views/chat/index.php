<?php defined('BASEPATH') OR exit('No direct script access allowed'); ?>
<!DOCTYPE html>
<html lang="en">
<head>
	<meta charset="utf-8">
	<meta name="viewport" content="width=device-width, initial-scale=1">
	<title>CMR Report Copilot</title>
	<link rel="stylesheet" href="<?php echo html_escape(base_url('assets/chat.css')); ?>">
</head>
<body>
<header class="topbar">
	<div>
		<strong>CMR Report Copilot</strong>
		<span class="muted">signed in as <?php echo html_escape($client['company']); ?> (<?php echo html_escape($client['id']); ?>)</span>
	</div>
	<?php echo form_open('chat/logout', array('class' => 'inline')); ?>
		<button type="submit" class="link">Sign out</button>
	<?php echo form_close(); ?>
</header>

<main class="chat">
	<div id="chat-config"
		data-ask-url="<?php echo html_escape(site_url('chat/ask')); ?>"
		data-feedback-url="<?php echo html_escape(site_url('chat/feedback')); ?>"
		data-csrf-name="<?php echo html_escape($this->security->get_csrf_token_name()); ?>"
		data-csrf-hash="<?php echo html_escape($this->security->get_csrf_hash()); ?>"></div>

	<section id="chat-log" aria-live="polite">
		<?php if (empty($history)): ?>
			<p class="muted hint">Ask about market sizes, forecasts or how reports compare. Every number comes with
				its source; derived figures are labelled; you will only see reports in your subscription.</p>
		<?php endif; ?>
		<?php foreach ($history as $h): ?>
			<div class="msg user"><?php echo html_escape($h['question']); ?></div>
			<div class="msg bot" data-conv-id="<?php echo (int) $h['id']; ?>">
				<div class="meta">
					<?php if ($h['status'] === 'fallback'): ?>
						<span class="badge warn">service unavailable</span>
					<?php else: ?>
						<span class="badge">confidence <?php echo html_escape(number_format((float) $h['confidence'], 2)); ?></span>
					<?php endif; ?>
					<?php if ((int) $h['escalated'] === 1): ?><span class="badge warn">escalated to analyst</span><?php endif; ?>
				</div>
				<div class="answer"><?php echo html_escape($h['answer']); ?></div>
				<div class="feedback">
					<button type="button" class="fb<?php echo ((int) $h['rating'] === 1) ? ' on' : ''; ?>" data-rating="1" aria-label="Helpful">&#128077;</button>
					<button type="button" class="fb<?php echo ((int) $h['rating'] === -1) ? ' on' : ''; ?>" data-rating="-1" aria-label="Not helpful">&#128078;</button>
				</div>
			</div>
		<?php endforeach; ?>
	</section>

	<form id="ask-form" autocomplete="off">
		<textarea id="question" name="question" maxlength="1000" rows="2" required
			placeholder="e.g. What will the APAC smart water meter market be worth in 2030?"></textarea>
		<button type="submit" id="ask-btn">Ask</button>
	</form>
</main>
<script src="<?php echo html_escape(base_url('assets/chat.js')); ?>"></script>
</body>
</html>
