FROM php:8.1-apache

RUN apt-get update \
 && apt-get install -y --no-install-recommends unzip \
 && rm -rf /var/lib/apt/lists/* \
 && docker-php-ext-install mysqli \
 && a2enmod headers

# CodeIgniter 3 framework from the official release; only our application/ overrides are in git.
ARG CI_VERSION=3.1.13
RUN curl -fsSL -o /tmp/ci3.zip "https://github.com/bcit-ci/CodeIgniter/archive/refs/tags/${CI_VERSION}.zip" \
 && unzip -q /tmp/ci3.zip -d /tmp \
 && mv "/tmp/CodeIgniter-${CI_VERSION}/system" /var/www/system \
 && mv "/tmp/CodeIgniter-${CI_VERSION}/application" /var/www/application \
 && cp "/tmp/CodeIgniter-${CI_VERSION}/index.php" /var/www/html/index.php \
 && rm -rf /tmp/ci3.zip "/tmp/CodeIgniter-${CI_VERSION}" \
 && sed -i "s|\$system_path = 'system';|\$system_path = '/var/www/system';|" /var/www/html/index.php \
 && sed -i "s|\$application_folder = 'application';|\$application_folder = '/var/www/application';|" /var/www/html/index.php

# Application code lives outside the web root; only index.php and static assets are served.
COPY application/ /var/www/application/
COPY public/ /var/www/html/
COPY apache-atlas.conf /etc/apache2/conf-enabled/atlas.conf

RUN mkdir -p /var/www/sessions \
 && chown -R www-data:www-data /var/www/sessions /var/www/application/logs /var/www/application/cache

EXPOSE 80
