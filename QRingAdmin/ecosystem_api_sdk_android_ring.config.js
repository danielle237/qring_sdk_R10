module.exports = {
  apps: [
    {
      name: 'api android qring',
      script: '/var/www/html/QRingAdmin_new/client_api.py',
      interpreter: '/usr/local/bin/python3.14',
      // Force le mode non-buffering pour Python
      interpreter_args: '-u', 
      autorestart: true,
      // Désactivez le watch pour empêcher les ralentissements d'I/O
      watch: false, 
      // Désactivez les logs si vous n'en avez pas besoin, 
      // ou redirigez-les vers /dev/null pour gagner en performance
      out_file: '/dev/null',
      error_file: '/dev/null',
      max_memory_restart: '5G',
      env_production: {
        NODE_ENV: 'production'
      }
    }
  ]
};