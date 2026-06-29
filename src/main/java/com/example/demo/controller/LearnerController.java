package com.example.demo.controller;

import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.beans.factory.annotation.Autowired;
import com.example.demo.service.LearnerManagementService;
import com.example.demo.entity.Learner;
import com.example.demo.dto.LearnerDTO;

import java.util.List;

@RestController
public class LearnerController {

    @Autowired
    private LearnerManagementService _learnerManagementService;

    @GetMapping("/learners")
    public List<LearnerDTO> getLearners() {
        return _learnerManagementService.getLearners();
    }

    @PostMapping("/learners")
    public Learner createLearner(@RequestBody Learner learner) {
        return _learnerManagementService.createLearner(learner);
    }   
}

