FROM openeuler/openeuler:22.03-lts-sp1

MAINTAINER TomNewChao<tom_toworld@163.com>

RUN mkdir -p /opt/pr-statistics

COPY . /opt/pr-statistics/

RUN yum update -y && yum install -y python3-pip git

RUN pip3 install -r /opt/pr-statistics/requirements.txt

WORKDIR /opt/pr-statistics

ENTRYPOINT ["python3", "/opt/pr-statistics/pr_statistics.py"]
