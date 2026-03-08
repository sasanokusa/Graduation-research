CREATE TABLE IF NOT EXISTS items (
  id INT PRIMARY KEY AUTO_INCREMENT,
  name VARCHAR(255) NOT NULL,
  description TEXT NOT NULL
);

INSERT INTO items (name, description)
VALUES ('seed-item', 'initial record for failure-recovery testing');
