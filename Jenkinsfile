pipeline {
  agent { label 'subman' }
  options {
    timeout(time: 10, unit: 'MINUTES')
  }
  stages {
    stage('Test') {
      parallel {
        stage('Pytest') {
          steps {
              sh readFile(file: 'jenkins/pytest.sh')          
          }
        }
        stage('stylish') {
          steps {
            sh readFile(file: 'jenkins/stylish.sh')
          }
        }
      }
    }
  }
}
