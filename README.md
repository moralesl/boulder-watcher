# SAM Boulder-Watcher

Watches the crowd level of the BoulderWelt [east](https://www.boulderwelt-muenchen-ost.de/), [south](https://www.boulderwelt-muenchen-sued.de/) and [west](https://www.boulderwelt-muenchen-west.de/).


## Architecture overview
![BoulderWatcher Architecture](docs/BoulderWatcher.png)


## Monitoring overview
![BoulderWatcher Monitoring Architecture](docs/BoulderWatcher_monitoring.png)


## Sample boulder API request
```bash
curl --location \
     --form 'action="cxo_get_crowd_indicator"' \
     --request POST \
     'https://www.boulderwelt-muenchen-west.de/wp-admin/admin-ajax.php'
```

## Maintaining the project
### Push to all remotes
```bash
git remote | xargs -L1 git push
```

### Build and deploy
```bash
sam build && sam deploy
```
