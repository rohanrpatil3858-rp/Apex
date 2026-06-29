package com.example.demo.repository;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import com.example.demo.entity.Learner;

@Repository
public interface LearnerRepository extends JpaRepository<Learner, Long> {

    

}
