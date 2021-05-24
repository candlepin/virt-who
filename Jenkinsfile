pipeline {
  agent { label 'subman' }
  options {
    timeout(time: 10, unit: 'MINUTES')
  }
  stages {
    stage('Pytest') {
      steps {
          sh readFile(file: 'jenkins/pytest.sh')
      }
    }
  }
}
