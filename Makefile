all: clean docker

clean:
	rm -rf build/ dist/ docker/*.whl docker/*.txt

py_wheel:
	python3 -m build --wheel

docker: py_wheel
	find dist  -iname '*.whl' -exec mv {} docker \;
	cat src/clippybot.egg-info/requires.txt | sort | grep -i '^[a-zA-Z].*' > docker/requirements.txt
	docker-compose --project-directory docker build