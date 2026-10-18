<?php defined('BASEPATH') OR exit('No direct script access allowed'); ?>
<!DOCTYPE html>
<html lang="en">
<head>
	<meta charset="utf-8">
	<meta name="viewport" content="width=device-width, initial-scale=1">
	<title>CMR Client Portal - Sign in</title>
	<link rel="stylesheet" href="<?php echo html_escape(base_url('assets/chat.css')); ?>">
</head>
<body>
<main class="login">
	<h1>CMR Client Portal</h1>
	<p class="muted">Demo sign-in. In production this page is replaced by the portal's existing login; the chat
		only ever uses the client id stored in the server-side session.</p>
	<?php if ($error): ?>
		<p class="error"><?php echo html_escape($error); ?></p>
	<?php endif; ?>
	<?php echo form_open('chat/login'); ?>
		<label for="client_id">Client account</label>
		<select name="client_id" id="client_id" required>
			<?php foreach ($clients as $c): ?>
				<option value="<?php echo html_escape($c['id']); ?>"><?php echo html_escape($c['id'] . ' - ' . $c['company']); ?></option>
			<?php endforeach; ?>
		</select>
		<button type="submit">Sign in</button>
	<?php echo form_close(); ?>
	<?php if (empty($clients)): ?>
		<p class="error">The client list could not be loaded. Is the database running?</p>
	<?php endif; ?>
</main>
</body>
</html>
